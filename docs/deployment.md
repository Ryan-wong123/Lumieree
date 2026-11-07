# Deployment runbook – AWS (EC2 + S3 + Kubernetes/k3s) with a DuckDNS domain

This is the step-by-step guide to put Lumieree on the public internet:

| Piece | Choice |
| --- | --- |
| Compute | **One EC2 instance** (Ubuntu 24.04, `t3.medium`) with a fixed **Elastic IP** |
| Kubernetes | **k3s** (lightweight, certified Kubernetes) installed on that instance |
| Database | **PostgreSQL 16** StatefulSet in the cluster (data on the instance's encrypted EBS volume) |
| S3 | **Private encrypted bucket** that receives nightly `pg_dump` backups |
| Domain + TLS | **DuckDNS** sub-domain → Elastic IP; **Let's Encrypt** certificate via cert-manager |
| Images | GitHub Container Registry (`ghcr.io/ryan-wong123/lumieree`), built by CI |

```mermaid
flowchart LR
    U[Users] -->|https://NAME.duckdns.org| EIP[Elastic IP]
    DNS[DuckDNS] -.->|A record| EIP
    subgraph EC2[EC2 t3.medium · k3s · encrypted gp3 volume]
        NGX[ingress-nginx :80/:443] --> WEB[lumieree-web x2]
        WEB --> PG[(PostgreSQL StatefulSet)]
        WEB --> RD[(Redis)]
        BK[CronJob pg_dump] --> PG
        CM[cert-manager] -. HTTP-01 .-> NGX
    end
    BK -->|IAM instance role, HTTPS| S3[(S3 backup bucket)]
```

> **Status of this guide.** Executed end to end on 2026-11-07 (AWS CloudShell as the deploy shell, `ap-southeast-1`).
> Corrections found on the way are marked "Tested note" below. Expect further small differences (versions, flags);
> if you find one, fix this file in the same change (see `AGENTS.md`).

> **Tested note – AWS Free plan.** New accounts on the Free plan cannot launch `t3.medium`
> (`InvalidParameterCombination … not eligible for Free Tier`). List eligible types with
> `aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true`; `c7i-flex.large` (2 vCPU, 4 GiB,
> amd64) has the same size as `t3.medium` and worked. Upgrading the account plan is the alternative.

**Trade-offs of this design (be aware):** a single EC2 node is a single point of failure (no HA; recovery = rebuild
from this guide + restore from S3); DuckDNS is a free third-party service without an SLA; k3s upgrades and OS
patching are your job. It is a good fit for one clinic / a pilot. For HA use EKS + RDS (see Appendix A).

---

## 0. Prerequisites and decisions

On the machine you deploy **from**:

* AWS CLI v2 configured (`aws sts get-caller-identity` works) with permissions for EC2, IAM, S3, SSM (read).
* `kubectl`, `helm` 3, `git`, `ssh`, `curl`, `openssl`, `dig`; `docker` only if you build the image yourself.
* A clone of this repository, branch/commit you intend to deploy.

Things to decide / gather first:

| Item | Example |
| --- | --- |
| AWS region | `ap-southeast-1` (Singapore) |
| DuckDNS sub-domain + token | create at <https://www.duckdns.org> (sign in, add a domain, copy the token) → `https://clinic-name.duckdns.org` |
| E-mail for Let's Encrypt | `you@example.com` |
| First super-admin username + a long password | not `admin`/`password` |
| Image tag to deploy | a git SHA pushed by CI (see §6) |

**Before the first public deployment**

1. **Revoke the old Firebase service-account key** (`lumiere-583de-firebase-adminsdk-…`). It was committed to the
   repository and is still in git history; assume it is compromised. Remove history with `git filter-repo` if the repo
   is or will be public.
2. Decide whether the legacy Firebase data must be imported (§12).

> **Instructions for an AI agent following this guide:** ask the human before creating billable AWS resources, never
> print or commit secrets (tokens, passwords, `SECRET_KEY`, PAT), keep the generated `*.pem` key out of the repo,
> record every resource id you create (you need them for teardown), and stop and report if a step fails rather than
> improvising.

---

## 1. Set variables (one shell session)

```bash
export AWS_REGION=ap-southeast-1
export AWS_PAGER=""
export APP=lumieree
export DUCK_SUBDOMAIN=your-subdomain          # => your-subdomain.duckdns.org
export LE_EMAIL=you@example.com
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export BUCKET=${APP}-backups-${ACCOUNT_ID}-${AWS_REGION}
export MY_IP=$(curl -s https://checkip.amazonaws.com)      # your public IP, for SSH access
read -rs -p "DuckDNS token: " DUCK_TOKEN; export DUCK_TOKEN; echo   # not stored in shell history
```

Keep this shell open (or re-export the variables later).

---

## 2. S3 bucket for backups

```bash
aws s3api create-bucket --bucket "$BUCKET" --region "$AWS_REGION" \
  --create-bucket-configuration LocationConstraint="$AWS_REGION"

aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

# Keep 30 days of backups; drop old versions after 7 days.
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration '{
  "Rules":[{"ID":"expire-old-backups","Status":"Enabled","Filter":{"Prefix":"postgres/"},
    "Expiration":{"Days":30},
    "NoncurrentVersionExpiration":{"NoncurrentDays":7},
    "AbortIncompleteMultipartUpload":{"DaysAfterInitiation":2}}]}'

# Refuse any non-TLS access.
aws s3api put-bucket-policy --bucket "$BUCKET" --policy "{
  \"Version\":\"2012-10-17\",
  \"Statement\":[{\"Sid\":\"DenyInsecureTransport\",\"Effect\":\"Deny\",\"Principal\":\"*\",
    \"Action\":\"s3:*\",\"Resource\":[\"arn:aws:s3:::${BUCKET}\",\"arn:aws:s3:::${BUCKET}/*\"],
    \"Condition\":{\"Bool\":{\"aws:SecureTransport\":\"false\"}}}]}"
```

## 3. IAM role for the instance (lets the backup job write to the bucket, nothing else)

```bash
aws iam create-role --role-name ${APP}-ec2 --assume-role-policy-document '{
  "Version":"2012-10-17",
  "Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

aws iam put-role-policy --role-name ${APP}-ec2 --policy-name backup-bucket --policy-document "{
  \"Version\":\"2012-10-17\",
  \"Statement\":[
    {\"Effect\":\"Allow\",\"Action\":[\"s3:PutObject\",\"s3:GetObject\"],\"Resource\":\"arn:aws:s3:::${BUCKET}/postgres/*\"},
    {\"Effect\":\"Allow\",\"Action\":\"s3:ListBucket\",\"Resource\":\"arn:aws:s3:::${BUCKET}\"}]}"

aws iam create-instance-profile --instance-profile-name ${APP}-ec2
aws iam add-role-to-instance-profile --instance-profile-name ${APP}-ec2 --role-name ${APP}-ec2
sleep 15   # let IAM propagate before launching the instance
```

## 4. Network, key pair, EC2 instance, Elastic IP

```bash
VPC_ID=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)

SG_ID=$(aws ec2 create-security-group --group-name ${APP} --description "Lumieree k3s" \
  --vpc-id "$VPC_ID" --query GroupId --output text)
# 80/443 from anywhere (web + Let's Encrypt validation); SSH only from your IP. Do NOT open 6443.
aws ec2 authorize-security-group-ingress --group-id "$SG_ID" --ip-permissions \
  "IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0}]" \
  "IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]" \
  "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=${MY_IP}/32,Description=admin-ssh}]"

aws ec2 create-key-pair --key-name ${APP} --query KeyMaterial --output text > ~/.ssh/${APP}.pem
chmod 400 ~/.ssh/${APP}.pem

AMI_ID=$(aws ssm get-parameter \
  --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
  --query Parameter.Value --output text)

# t3.medium (2 vCPU, 4 GiB) is the practical minimum for app x2 + PostgreSQL + Redis + ingress + cert-manager.
# IMDSv2 required; hop limit 2 so the backup pod (and only it, see NetworkPolicy) can use the instance role.
INSTANCE_ID=$(aws ec2 run-instances --image-id "$AMI_ID" --instance-type t3.medium \
  --key-name ${APP} --security-group-ids "$SG_ID" --iam-instance-profile Name=${APP}-ec2 \
  --metadata-options HttpTokens=required,HttpPutResponseHopLimit=2,HttpEndpoint=enabled \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=30,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${APP}}]" \
  --query 'Instances[0].InstanceId' --output text)
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"

ALLOC_ID=$(aws ec2 allocate-address --domain vpc --query AllocationId --output text)
aws ec2 associate-address --instance-id "$INSTANCE_ID" --allocation-id "$ALLOC_ID"
export EIP=$(aws ec2 describe-addresses --allocation-ids "$ALLOC_ID" --query 'Addresses[0].PublicIp' --output text)
echo "INSTANCE_ID=$INSTANCE_ID  SG_ID=$SG_ID  ALLOC_ID=$ALLOC_ID  EIP=$EIP"   # write these down for teardown
```

## 5. DuckDNS → Elastic IP

DuckDNS maps a name to an IP address only (no CNAME), which is why the instance has a fixed Elastic IP.

```bash
curl -s "https://www.duckdns.org/update?domains=${DUCK_SUBDOMAIN}&token=${DUCK_TOKEN}&ip=${EIP}"; echo   # must print OK
dig +short ${DUCK_SUBDOMAIN}.duckdns.org                                                                  # must print $EIP
```

Because the IP never changes, no update cron job is needed. (If you ever replace the Elastic IP, run the first
command again.) Treat the token like a password.

## 6. Container image

CI (`.github/workflows/ci.yml`) pushes `ghcr.io/<owner>/lumieree:<git-sha>` **only from the `main` branch**, so first
merge the `new-improvement` pull request, then use the SHA of the merge commit. Or build and push yourself:

```bash
TAG=$(git rev-parse --short=12 HEAD)
echo "$GHCR_PAT" | docker login ghcr.io -u ryan-wong123 --password-stdin     # PAT with write:packages
docker build --platform linux/amd64 -t ghcr.io/ryan-wong123/lumieree:${TAG} .   # EC2 t3 is amd64 (matters on Apple Silicon)
docker push ghcr.io/ryan-wong123/lumieree:${TAG}
```

Visibility of the image: simplest is to make the package **public** (GitHub → your profile → Packages → `lumieree`
→ Package settings → Change visibility); the image contains no secrets. To keep it private, create a pull secret in §9
(`ghcr-pull`, a PAT with `read:packages`); the overlay already references it.

## 7. Install k3s on the instance and reach it from your laptop

```bash
ssh -i ~/.ssh/${APP}.pem ubuntu@${EIP}
```

On the instance:

```bash
sudo apt-get update && sudo apt-get -y upgrade
sudo apt-get -y install unattended-upgrades          # automatic security patches
# Pick a current stable k3s version from https://github.com/k3s-io/k3s/releases and pin it:
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="v1.31.4+k3s1" \
  INSTALL_K3S_EXEC="server --disable traefik --write-kubeconfig-mode 600" sh -
sudo k3s kubectl get nodes        # STATUS Ready
exit
```

(`--disable traefik` because we use ingress-nginx; k3s keeps its bundled metrics-server for the autoscaler, the
`local-path` storage class for PostgreSQL, and the built-in NetworkPolicy controller, so the policies in `k8s/` are
enforced.) Port 6443 is not exposed, so use an SSH tunnel from your laptop:

```bash
mkdir -p ~/.kube
ssh -i ~/.ssh/${APP}.pem ubuntu@${EIP} 'sudo cat /etc/rancher/k3s/k3s.yaml' > ~/.kube/${APP}.yaml
chmod 600 ~/.kube/${APP}.yaml
ssh -i ~/.ssh/${APP}.pem -N -L 6443:127.0.0.1:6443 ubuntu@${EIP} &      # keep running while you use kubectl
export KUBECONFIG=~/.kube/${APP}.yaml
kubectl get nodes
```

## 8. Cluster add-ons: ingress-nginx and cert-manager

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add jetstack https://charts.jetstack.io
helm repo update

# externalTrafficPolicy=Local keeps the real client IP (needed for per-IP login rate limiting).
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace \
  --version 4.11.3 --set controller.service.type=LoadBalancer \
  --set controller.service.externalTrafficPolicy=Local
kubectl -n ingress-nginx get svc ingress-nginx-controller      # EXTERNAL-IP = the node's private IP (k3s ServiceLB)

helm upgrade --install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --version v1.16.2 --set crds.enabled=true        # use >= 1.15 so HTTP-01 solver pods satisfy Pod Security "restricted"
kubectl -n cert-manager rollout status deploy/cert-manager-webhook

sed "s/you@example.com/${LE_EMAIL}/g" k8s/addons/cluster-issuer.yaml | kubectl apply -f -
```

## 9. Namespace, secrets and configuration

```bash
kubectl apply -f k8s/base/namespace.yaml

PG_PASS=$(openssl rand -hex 24)                       # hex => safe inside the DATABASE_URL
kubectl -n lumieree create secret generic postgres-credentials --from-literal=POSTGRES_PASSWORD="$PG_PASS"

read -rs -p "Bootstrap super-admin password (12+ chars): " ADMIN_PW; echo
kubectl -n lumieree create secret generic lumieree-secrets \
  --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=DATABASE_URL="postgresql+psycopg://lumieree:${PG_PASS}@postgres:5432/lumieree" \
  --from-literal=BOOTSTRAP_ADMIN_USERNAME="your-admin-username" \
  --from-literal=BOOTSTRAP_ADMIN_PASSWORD="$ADMIN_PW"
unset PG_PASS ADMIN_PW

kubectl -n lumieree create configmap lumieree-backup \
  --from-literal=BACKUP_BUCKET="$BUCKET" --from-literal=AWS_DEFAULT_REGION="$AWS_REGION"

# Only if the GHCR package is private:
# kubectl -n lumieree create secret docker-registry ghcr-pull --docker-server=ghcr.io \
#   --docker-username=ryan-wong123 --docker-password="$GHCR_READ_PAT"
```

Put the clinic's receipt header in `k8s/base/configmap.yaml` (`CLINIC_NAME`, `CLINIC_NAME_ZH`, `CLINIC_REG_NO`,
`CLINIC_ADDRESS`). Secrets live only in the cluster; never commit them.

## 10. Point the overlay at your domain and image, then deploy

```bash
TAG=<the image tag from §6>     # CI tags images with the FULL 40-character commit SHA (github.sha), not the short form
sed -i "s/CHANGE-ME.duckdns.org/${DUCK_SUBDOMAIN}.duckdns.org/g" k8s/overlays/aws-k3s/kustomization.yaml
sed -i "s#newTag: latest#newTag: ${TAG}#" k8s/overlays/aws-k3s/kustomization.yaml

kubectl apply -k k8s/overlays/aws-k3s
kubectl -n lumieree rollout status statefulset/postgres --timeout=300s

# First deploy and every release: migrate BEFORE the app serves traffic (Jobs are immutable, so replace it).
kubectl -n lumieree delete job lumieree-migrate --ignore-not-found
sed "s#ghcr.io/ryan-wong123/lumieree:latest#ghcr.io/ryan-wong123/lumieree:${TAG}#" k8s/base/migrate-job.yaml | kubectl apply -f -
kubectl -n lumieree wait --for=condition=complete job/lumieree-migrate --timeout=300s
kubectl -n lumieree logs job/lumieree-migrate | tail     # "Super admin created" on the first run

kubectl -n lumieree rollout status deploy/lumieree-web --timeout=300s
```

## 11. Verify

```bash
kubectl -n lumieree get pods,certificate,ingress
kubectl -n lumieree get challenge,order 2>/dev/null          # empty once the certificate is Ready
curl -s https://${DUCK_SUBDOMAIN}.duckdns.org/healthz        # {"status":"ok"}
curl -s https://${DUCK_SUBDOMAIN}.duckdns.org/readyz         # {"status":"ready"}
curl -sI http://${DUCK_SUBDOMAIN}.duckdns.org | head -3       # 308 redirect to https
```

Open `https://<your-subdomain>.duckdns.org`, sign in as the bootstrap admin, create a clinic account under
*Super Admin → Create new user*, and click through patients → visit → front desk → receipt.

**Test the backup path now** (not after the first incident):

```bash
kubectl -n lumieree create job --from=cronjob/postgres-backup-s3 backup-test
kubectl -n lumieree wait --for=condition=complete job/backup-test --timeout=300s
kubectl -n lumieree logs job/backup-test -c upload                # uploaded s3://…/postgres/lumieree-….dump
aws s3 ls s3://$BUCKET/postgres/
kubectl -n lumieree delete job backup-test
```

## 12. Optional: import the legacy Firebase data (once)

```bash
pip install -r requirements-migrate.txt
kubectl -n lumieree port-forward svc/postgres 15432:5432 &            # temporary local access to the DB
export DATABASE_URL="postgresql+psycopg://lumieree:<PG_PASS>@127.0.0.1:15432/lumieree"   # APP_ENV=development locally
export SECRET_KEY=local-only-not-used-in-production-0123456789
flask --app wsgi import-firestore --credentials /secure/path/firebase-key.json --dry-run
flask --app wsgi import-firestore --credentials /secure/path/firebase-key.json
```

(`svc/postgres` is headless; if `port-forward` complains, use `kubectl -n lumieree port-forward pod/postgres-0 15432:5432`.)
The command writes `migrated-credentials.csv` (mode 600) with a random temporary password per user. Hand them out
securely, delete the file, and stop the port-forward. Users must choose a new password at first login. Firestore
`prescriptions` (legacy, no UI) are not migrated.

---

## 13. Day-2 operations

**Release a new version** – merge to `main`, wait for CI to publish `:<sha>`, then repeat §10 with the new `TAG`
(migrate Job first, then `kubectl apply -k`, then `rollout status`).

**Roll back the app** – `kubectl -n lumieree rollout undo deploy/lumieree-web`. Migrations are expand/contract, so
the previous image keeps working with the new schema for one release; run `flask db downgrade` only after a backup.

**Restore from S3** (also the disaster-recovery path: rebuild the instance with §1–§10, then restore):

```bash
aws s3 ls s3://$BUCKET/postgres/
aws s3 cp s3://$BUCKET/postgres/<file>.dump ./lumieree.dump
kubectl -n lumieree cp lumieree.dump postgres-0:/tmp/lumieree.dump
kubectl -n lumieree exec postgres-0 -- pg_restore --clean --if-exists --no-owner -U lumieree -d lumieree /tmp/lumieree.dump
kubectl -n lumieree exec postgres-0 -- rm /tmp/lumieree.dump
```

Rehearse a restore into a scratch namespace or instance at least once. Optionally add daily EBS snapshots (AWS Data
Lifecycle Manager) as a second layer.

**Logs / status** – `kubectl -n lumieree logs deploy/lumieree-web --tail=100`, `kubectl -n lumieree get pods`,
`kubectl top pods -n lumieree`.

**Patching** – unattended-upgrades handles OS security patches (schedule an occasional reboot:
`ssh … sudo reboot`; pods come back by themselves). Upgrade k3s by re-running the installer with a newer
`INSTALL_K3S_VERSION`; upgrade Helm add-ons with `helm upgrade`. Keep `requirements.txt` and the base image current.

**Cost** – roughly one `t3.medium`, 30 GiB gp3, one public IPv4/Elastic IP (charged hourly), a few cents of S3 and
data transfer; check current AWS pricing for your region. Stop nothing casually: a stopped instance still pays for
storage and the Elastic IP.

**Rotate secrets** – `SECRET_KEY` (logs everyone out): recreate `lumieree-secrets`, then
`kubectl -n lumieree rollout restart deploy/lumieree-web`. DuckDNS token: regenerate on duckdns.org.

### Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| Certificate stays `False` / challenge `pending` | DNS does not point at the Elastic IP yet; security group lacks port 80; solver NetworkPolicy missing (`kubectl -n lumieree get netpol`); check `kubectl describe challenge -n lumieree`. Use `letsencrypt-staging` while debugging |
| Browser shows the Kubernetes "fake" certificate | Certificate not issued yet; wait or see the row above |
| `ImagePullBackOff` | Wrong tag, package private without `ghcr-pull`, or the image was built for the wrong CPU (`--platform linux/amd64`) |
| `502` / `503` from nginx | App pods not ready: `kubectl -n lumieree describe pod`, `logs`; migrate Job not completed; wrong `DATABASE_URL` |
| App pods crash with `SECRET_KEY must be set…` | `lumieree-secrets` missing or key shorter than 32 characters |
| Login works but rate limiting hits everyone | Client IP not preserved: confirm `externalTrafficPolicy=Local` and `TRUSTED_PROXY_COUNT=1` |
| Backup job fails with `Unable to locate credentials` | Instance profile not attached, IMDS hop limit not 2 (`aws ec2 modify-instance-metadata-options --instance-id $INSTANCE_ID --http-put-response-hop-limit 2 --http-tokens required`), or the `backup` NetworkPolicy missing |
| `kubectl` cannot connect | SSH tunnel not running; `KUBECONFIG` not exported |
| Everything is down after an instance reboot | Wait 2–3 minutes for k3s and pods; check `sudo systemctl status k3s` |

## 14. Teardown (stops all charges)

Back up first (§13). Then, with the variables from §1/§4 exported:

```bash
aws ec2 terminate-instances --instance-ids "$INSTANCE_ID" && aws ec2 wait instance-terminated --instance-ids "$INSTANCE_ID"
aws ec2 release-address --allocation-id "$ALLOC_ID"
aws ec2 delete-security-group --group-id "$SG_ID"
aws ec2 delete-key-pair --key-name ${APP} && rm -f ~/.ssh/${APP}.pem
aws iam remove-role-from-instance-profile --instance-profile-name ${APP}-ec2 --role-name ${APP}-ec2
aws iam delete-instance-profile --instance-profile-name ${APP}-ec2
aws iam delete-role-policy --role-name ${APP}-ec2 --policy-name backup-bucket && aws iam delete-role --role-name ${APP}-ec2
# The bucket is versioned: delete all versions first (or use the console "Empty" button), then:
aws s3api delete-bucket --bucket "$BUCKET"
```

Delete the DuckDNS domain on duckdns.org if you no longer need it.

## 15. Hardening checklist

- [ ] Old Firebase key revoked; repository history cleaned if public
- [ ] SSH restricted to your IP (re-run the `authorize`/`revoke` commands if your IP changes); port 6443 closed
- [ ] `SECRET_KEY` random (≥ 32 chars), bootstrap password long and changed after first login
- [ ] HTTPS works and HTTP redirects; `SESSION_COOKIE_SECURE=true` (already in the ConfigMap)
- [ ] Backups verified by a real restore; bucket private, versioned, encrypted, TLS-only
- [ ] Image tag is a git SHA (not `latest`); OS and k3s kept patched
- [ ] Only the backup pod can reach the instance metadata service (NetworkPolicies in `k8s/`)

---

## Appendix A – Other Kubernetes clusters (EKS, GKE, on-prem)

The base manifests are cluster-agnostic. Use `k8s/overlays/production` with a managed PostgreSQL (set `DATABASE_URL` to
it, ideally with `?sslmode=require`), install ingress-nginx and cert-manager as in §8 (apply
`k8s/addons/cluster-issuer.yaml`), create `lumieree-secrets` as in §9 (no `postgres-credentials` needed), edit the
overlay hostname/image tag, then run the migrate Job and `kubectl apply -k k8s/overlays/production` as in §10. On EKS
prefer RDS for PostgreSQL, ECR or GHCR for images, and a Route 53 record (or ExternalDNS) instead of DuckDNS.

## Appendix B – Local run with docker compose

```bash
export BOOTSTRAP_ADMIN_USERNAME=admin BOOTSTRAP_ADMIN_PASSWORD='choose-a-long-password'
docker compose up --build        # http://localhost:8080  (db -> migrate -> web)
# behind a TLS-inspecting proxy: docker build --secret id=pip_ca,src=/path/to/ca-bundle.crt .
```

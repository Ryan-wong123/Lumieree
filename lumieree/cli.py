"""Operational CLI commands (``flask <command>``)."""

from __future__ import annotations

import click
from flask import Flask

from .auth import create_user
from .extensions import db
from .models import User
from .utils import ValidationError


def register_cli(app: Flask) -> None:
    register_import_cli(app)

    @app.cli.command("create-super-admin")
    @click.option("--username", prompt=True, help="Login name for the super admin")
    @click.option("--email", default=None, help="Optional contact email")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_super_admin(username, email, password):
        """Create a super admin account (the only way to create one)."""
        try:
            user = create_user(username, password, role="super_admin", email=email)
        except ValidationError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"Super admin created: {user.username} (id {user.id})")

    @app.cli.command("ensure-super-admin")
    def ensure_super_admin():
        """Idempotent bootstrap for deployments: reads BOOTSTRAP_ADMIN_USERNAME / _PASSWORD / _EMAIL.

        Creates the account only if no super admin exists yet, then exits 0 either way.
        """
        import os

        if db.session.scalar(db.select(db.func.count(User.id)).where(User.role == "super_admin")):
            click.echo("A super admin already exists; nothing to do.")
            return
        username = os.environ.get("BOOTSTRAP_ADMIN_USERNAME")
        password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")
        if not username or not password:
            raise click.ClickException("BOOTSTRAP_ADMIN_USERNAME and BOOTSTRAP_ADMIN_PASSWORD are required.")
        try:
            user = create_user(username, password, role="super_admin", email=os.environ.get("BOOTSTRAP_ADMIN_EMAIL"))
        except ValidationError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(f"Super admin created: {user.username}")


def register_import_cli(app: Flask) -> None:
    @app.cli.command("import-firestore")
    @click.option(
        "--credentials",
        required=True,
        type=click.Path(exists=True, dir_okay=False),
        help="Firebase service-account JSON",
    )
    @click.option(
        "--output", default="migrated-credentials.csv", show_default=True, help="Where to write temporary passwords"
    )
    @click.option("--dry-run", is_flag=True, help="Run the whole import, then roll back")
    @click.option("--force", is_flag=True, help="Import even if the users table is not empty")
    def import_firestore(credentials, output, dry_run, force):
        """One-off migration of legacy Firebase data into PostgreSQL (see docs/deployment.md)."""
        from .legacy_import import FirestoreSource, import_all, write_credentials

        if not force and db.session.scalar(db.select(db.func.count(User.id))):
            raise click.ClickException("The database already has users. Use --force to import anyway.")
        report = import_all(FirestoreSource(credentials), commit=not dry_run)
        click.echo(f"Imported: {report.counts}")
        click.echo(f"Skipped:  {report.skipped}")
        if dry_run:
            click.echo("Dry run: nothing was written.")
            return
        write_credentials(report, output)
        click.echo(
            f"Temporary credentials written to {output} (mode 600). Hand them out securely, then delete the file."
        )

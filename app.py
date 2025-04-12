# Flask TCM POS App — Full Scaffold with Routing, Templates, and Firebase
# This will include inventory, patients, prescriptions, front desk queue, and receipt functionality.

from flask import Flask, render_template, request, redirect, url_for, flash
from firebase_admin import credentials, firestore, initialize_app
import datetime
from pyzbar.pyzbar import decode
from PIL import Image
import io

app = Flask(__name__)
app.secret_key = 'your-secret-key'

# Firebase Initialization
cred = credentials.Certificate("lumiere-583de-firebase-adminsdk-fbsvc-1501d71f13.json")
initialize_app(cred)
db = firestore.client()

# ================= Inventory =================
@app.route('/inventory')
def inventory():
    medicines = db.collection('medicines').stream()
    return render_template('inventory.html', medicines=[{**m.to_dict(), 'id': m.id} for m in medicines])

@app.route('/inventory/add', methods=['GET', 'POST'])
def add_medicine():
    if request.method == 'POST':
        data = request.form.to_dict()
        data['price'] = float(data['price'])
        data['stock'] = int(data['stock'])
        data['expiry_date'] = data['expiry_date']
        db.collection('medicines').add(data)
        flash('Medicine added successfully!')
        return redirect(url_for('inventory'))
    return render_template('add_medicine.html')

@app.route('/inventory/scan', methods=['POST'])
def scan_barcode():
    barcode = request.form['barcode']
    query = db.collection('medicines').where('barcode', '==', barcode).limit(1).stream()
    med = next(query, None)
    if med:
        doc = med.to_dict()
        db.collection('medicines').document(med.id).update({
            'stock': doc.get('stock', 0) + 1
        })
        flash(f"Stock updated for {doc['name']}.")
    else:
        flash("Barcode not found. Please add new medicine.")
    return redirect(url_for('inventory'))


@app.route('/inventory/scan-image', methods=['POST'])
def scan_image():
    file = request.files.get('barcode_image')
    if not file:
        flash("No image uploaded.")
        return redirect(url_for('inventory'))

    image = Image.open(file.stream)
    decoded = decode(image)

    if not decoded:
        flash("No barcode detected.")
        return redirect(url_for('inventory'))

    barcode = decoded[0].data.decode('utf-8')
    query = db.collection('medicines').where('barcode', '==', barcode).limit(1).stream()
    med = next(query, None)

    if med:
        doc = med.to_dict()
        db.collection('medicines').document(med.id).update({
            'stock': doc.get('stock', 0) + 1
        })
        flash(f"Stock updated for {doc['name']} (Barcode: {barcode})")
    else:
        flash(f"Barcode {barcode} not found in database.")

    return redirect(url_for('inventory'))

# ================= Patients =================
@app.route('/patients')
def patients():
    patient_list = db.collection('patients').stream()
    return render_template('patients.html', patients=[{**p.to_dict(), 'id': p.id} for p in patient_list])

@app.route('/patients/add', methods=['GET', 'POST'])
def add_patient():
    if request.method == 'POST':
        data = request.form.to_dict()
        data['last_visit'] = datetime.datetime.now().isoformat()
        db.collection('patients').add(data)
        flash('Patient added!')
        return redirect(url_for('patients'))
    return render_template('add_patient.html')

# ================= Prescriptions =================
@app.route('/prescriptions/create', methods=['GET', 'POST'])
def create_prescription():
    if request.method == 'POST':
        patient_id = request.form['patient_id']
        total = float(request.form['total'])
        items = []
        for i in range(len(request.form.getlist('medicine_id'))):
            items.append({
                'medicine_id': request.form.getlist('medicine_id')[i],
                'name': request.form.getlist('medicine_name')[i],
                'quantity': int(request.form.getlist('quantity')[i]),
                'unit_price': float(request.form.getlist('unit_price')[i])
            })
        doc = db.collection('prescriptions').add({
            'patient_id': patient_id,
            'items': items,
            'total': total,
            'timestamp': datetime.datetime.now().isoformat(),
            'sent_to_front_desk': True
        })
        db.collection('front_desk_queue').add({
            'prescription_id': doc[1].id,
            'status': 'waiting',
            'timestamp': datetime.datetime.now().isoformat()
        })
        flash("Prescription submitted.")
        return redirect(url_for('receipt', prescription_id=doc[1].id))

    medicines = db.collection('medicines').stream()
    patients = db.collection('patients').stream()
    return render_template('create_prescription.html', medicines=medicines, patients=patients)

# ================= Receipt View =================
@app.route('/receipt/<prescription_id>')
def receipt(prescription_id):
    presc_doc = db.collection('prescriptions').document(prescription_id).get()
    data = presc_doc.to_dict()
    patient = db.collection('patients').document(data['patient_id']).get().to_dict()
    return render_template('receipt.html', patient=patient, items=data['items'], total=data['total'])

# ================= Front Desk View =================
@app.route('/front_desk')
def front_desk():
    queue = db.collection('front_desk_queue').order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
    items = []
    for entry in queue:
        doc = entry.to_dict()
        prescription = db.collection('prescriptions').document(doc['prescription_id']).get().to_dict()
        patient = db.collection('patients').document(prescription['patient_id']).get().to_dict()
        items.append({
            'id': entry.id,
            'status': doc['status'],
            'patient_name': patient['name'],
            'items': prescription['items'],
        })
    return render_template('front_desk.html', queue=items)

@app.route('/front_desk/update/<queue_id>/<status>')
def update_queue_status(queue_id, status):
    db.collection('front_desk_queue').document(queue_id).update({ 'status': status })
    return redirect(url_for('front_desk'))

# ================= Run =================
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

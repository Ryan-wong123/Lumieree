# Flask TCM POS App — Full Scaffold with Routing, Templates, and Firebase
# This will include inventory, patients, prescriptions, front desk queue, and receipt functionality.

from flask import Flask, render_template, request, redirect, url_for, flash
from firebase_admin import credentials, firestore, initialize_app
from datetime import datetime
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
    query = request.args.get('q', '').strip().lower()
    medicines_ref = db.collection('medicines')
    all_docs = medicines_ref.stream()

    medicines = []
    for doc in all_docs:
        data = doc.to_dict()
        # If searching, filter by name or barcode (case-insensitive)
        if query:
            if query in data.get('name', '').lower() or query in data.get('barcode', '').lower():
                medicines.append(data)
        else:
            medicines.append(data)

    return render_template('inventory.html', medicines=medicines)

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
@app.route('/inventory/scan-combined', methods=['POST'])
def scan_combined():
    file = request.files.get('barcode_image')
    manual_barcode = request.form.get('manual_barcode', '').strip()
    barcode = manual_barcode  # fallback

    # Check barcode presence
    if not barcode:
        flash("❌ No barcode provided.")
        return redirect(url_for('inventory'))

    # Get quantity and adjust type
    try:
        amount = int(request.form.get('adjust_amount', 1))
        if amount < 1:
            raise ValueError
    except ValueError:
        flash("❌ Invalid quantity.")
        return redirect(url_for('inventory'))

    adjust_type = request.form.get('adjust_type', 'increase')

    # Find medicine by barcode
    query = db.collection('medicines').where('barcode', '==', barcode).limit(1).stream()
    med = next(query, None)

    if not med:
        flash(f"❌ Medicine with barcode {barcode} not found.")
        return redirect(url_for('inventory'))

    doc = med.to_dict()
    current_stock = doc.get('stock', 0)

    if adjust_type == 'decrease':
        new_stock = max(current_stock - amount, 0)
    else:
        new_stock = current_stock + amount

    db.collection('medicines').document(med.id).update({'stock': new_stock})

    flash(f"✅ Stock {'decreased' if adjust_type == 'decrease' else 'increased'} by {amount}. New stock: {new_stock}")
    return redirect(url_for('inventory'))


# ================= Patients =================
@app.route('/patients')
def patients():
    query = request.args.get('q', '').strip().lower()
    patient_list = db.collection('patients').stream()
    patients = []

    for p in patient_list:
        data = p.to_dict()
        data['id'] = p.id
        visits = db.collection('patients').document(p.id).collection('visits').stream()
        data['visit_count'] = sum(1 for _ in visits)

        if query:
            if query in data.get('name', '').lower() or query in data.get('contact', '').lower():
                patients.append(data)
        else:
            patients.append(data)

    return render_template('patients.html', patients=patients)


@app.route('/patients/add', methods=['GET', 'POST'])
def add_patient():
    if request.method == 'POST':
        data = request.form.to_dict()
        data['created_at'] = datetime.datetime.now().isoformat()
        data['last_visit'] = datetime.datetime.now().isoformat()
        db.collection('patients').add(data)
        flash('Patient added!')
        return redirect(url_for('patients'))
    return render_template('add_patient.html')

@app.route('/patients/edit/<id>', methods=['GET', 'POST'])
def edit_patient(id):
    patient_ref = db.collection('patients').document(id)

    if request.method == 'POST':
        data = request.form.to_dict()
        data['updated_at'] = datetime.datetime.now().isoformat()
        patient_ref.update(data)
        flash('Patient updated successfully!')
        return redirect(url_for('patients'))

    patient = patient_ref.get().to_dict()
    patient['id'] = id
    return render_template('edit_patient.html', patient=patient)

@app.route('/patients/<id>/visits', methods=['GET', 'POST'])
def patient_visits(id):
    patient_ref = db.collection('patients').document(id)
    patient = patient_ref.get().to_dict()
    patient['id'] = id

    if request.method == 'POST':
        visit = {
            'date': request.form.get('date') or datetime.now().date().isoformat(),
            'condition': request.form.get('condition'),
            'notes': request.form.get('notes'),
            'prescribed_meds': request.form.get('prescribed_meds'),
            'created_at': datetime.now().isoformat()
        }
        patient_ref.collection('visits').add(visit)
        flash('Visit added successfully.')
        return redirect(url_for('patient_visits', id=id))

    visits = patient_ref.collection('visits').order_by('date', direction=firestore.Query.DESCENDING).stream()
    return render_template('patient_visits.html', patient=patient, visits=[{**v.to_dict(), 'id': v.id} for v in visits])

@app.context_processor
def inject_now():
    return { 'now': datetime.now }

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

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

@app.route('/api/medicines')
def get_medicine_names():
    meds = db.collection('medicines').stream()
    names = [m.to_dict().get('name', '') for m in meds if m.to_dict().get('name')]
    return {'results': names}


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
            if (
                query in data.get('name', '').lower() or
                query in data.get('contact', '').lower() or
                query in data.get('nric', '').lower()
            ):
                patients.append(data)
        else:
            patients.append(data)

    return render_template('patients.html', patients=patients)

@app.route('/patients/add', methods=['GET', 'POST'])
def add_patient():
    if request.method == 'POST':
        data = request.form.to_dict()
        data['created_at'] = datetime.now().isoformat()
        data['last_visit'] = datetime.now().isoformat()
        db.collection('patients').add(data)
        flash('Patient added!')
        return redirect(url_for('patients'))
    return render_template('add_patient.html')


@app.route('/patients/edit/<id>', methods=['GET', 'POST'])
def edit_patient(id):
    patient_ref = db.collection('patients').document(id)

    if request.method == 'POST':
        data = request.form.to_dict()
        data['updated_at'] = datetime.now().isoformat()
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
        # Get all prescription rows
        names = request.form.getlist('med_name')
        quantities = request.form.getlist('med_quantity')
        dosages = request.form.getlist('med_dosage')

        prescribed_meds = []
        for i in range(len(names)):
            prescribed_meds.append({
                'name': names[i],
                'quantity': int(quantities[i]),
                'dosage': dosages[i]
            })

        visit = {
            'date': request.form.get('date') or datetime.now().date().isoformat(),
            'condition': request.form.get('condition'),
            'notes': request.form.get('notes'),
            'prescribed_meds': prescribed_meds,
            'created_at': datetime.now().isoformat()
        }

        patient_ref.collection('visits').add(visit)

        # Optionally send to front desk
        if prescribed_meds:
            db.collection('front_desk_queue').add({
                'patient_id': id,
                'items': prescribed_meds,
                'status': 'waiting',
                'timestamp': datetime.now().isoformat()
            })

        flash('Visit added.')
        return redirect(url_for('patient_visits', id=id))

    visits = patient_ref.collection('visits').order_by('date', direction=firestore.Query.DESCENDING).stream()
    visits = [{**v.to_dict(), 'id': v.id} for v in visits]

    # ✅ Get medicine names for datalist autocomplete
    med_names = [m.to_dict().get('name') for m in db.collection('medicines').stream()]

    return render_template('patient_visits.html', patient=patient, visits=visits, medicine_names=med_names)

@app.route('/patients/delete/<id>', methods=['POST'])
def delete_patient(id):
    patient_ref = db.collection('patients').document(id)

    # Delete all visit subcollection documents
    visits = patient_ref.collection('visits').stream()
    for v in visits:
        v.reference.delete()

    # Delete the patient document
    patient_ref.delete()

    flash('✅ Patient and all their visit records deleted.')
    return redirect(url_for('patients'))


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
@app.route('/receipt/queue/<queue_id>')
def queue_receipt(queue_id):
    queue_ref = db.collection('front_desk_queue').document(queue_id)
    queue_data = queue_ref.get().to_dict()

    # ✅ 1. Update status
    queue_ref.update({'status': 'completed'})

    # ✅ 3. Build receipt
    patient = db.collection('patients').document(queue_data['patient_id']).get().to_dict()
    items = []
    total = 0.0

    for i in queue_data.get('items', []):
        med_query = db.collection('medicines').where('name', '==', i['name']).limit(1).stream()
        med = next(med_query, None)
        if med:
            med_data = med.to_dict()
            subtotal = float(med_data['price']) * int(i['quantity'])
            total += subtotal
            items.append({
                'name': med_data['name'],
                'unit_price': med_data['price'],
                'quantity': i['quantity'],
                'subtotal': subtotal
            })
        else:
            items.append({
                'name': i['name'],
                'unit_price': 0.0,
                'quantity': i['quantity'],
                'subtotal': 0.0
            })

    return render_template('reciepts.html', patient=patient, items=items, total=round(total, 2))



# ================= Front Desk View =================
@app.route('/front_desk')
def front_desk():
    queue = db.collection('front_desk_queue').order_by('timestamp', direction=firestore.Query.DESCENDING).stream()
    
    waiting, prepared, completed = [], [], []

    for entry in queue:
        doc = entry.to_dict()
        patient = db.collection('patients').document(doc['patient_id']).get().to_dict()

        # ✅ Safeguard against missing patient
        if not patient:
            patient = {'name': '❌ Unknown (Deleted)', 'id': doc.get('patient_id', 'N/A')}

        item = {
            'id': entry.id,
            'status': doc.get('status'),
            'patient_name': patient.get('name', 'Unknown'),
            'items': doc.get('items', []),
        }

        status = doc.get('status')
        if status == 'waiting':
            waiting.append(item)
        elif status == 'prepared':
            prepared.append(item)
        elif status == 'completed':
            completed.append(item)

    return render_template('front_desk.html', waiting=waiting, prepared=prepared, completed=completed)

@app.route('/front_desk/update/<queue_id>/<status>')
def update_queue_status(queue_id, status):
    queue_ref = db.collection('front_desk_queue').document(queue_id)
    queue_doc = queue_ref.get().to_dict()

    if status == 'completed':
        # ✅ Decrement stock when completed
        items = queue_doc.get('items', [])
        for med in items:
            query = db.collection('medicines').where('name', '==', med['name']).limit(1).stream()
            found = next(query, None)
            if found:
                ref = db.collection('medicines').document(found.id)
                med_doc = found.to_dict()
                new_stock = max(med_doc.get('stock', 0) - int(med['quantity']), 0)
                ref.update({'stock': new_stock})

        queue_ref.update({'status': 'completed'})
        return redirect(url_for('queue_receipt', queue_id=queue_id))

    # 🟡 Just update status if not completed
    queue_ref.update({'status': status})
    return redirect(url_for('front_desk'))

@app.route('/admin/dashboard')
def admin_dashboard():
    from collections import Counter
    today = datetime.now().date().isoformat()

    # Count total patients
    total_patients = len(list(db.collection('patients').stream()))

    # Count visits today
    daily_visits = 0
    visits_ref = db.collection_group('visits').stream()
    for visit in visits_ref:
        data = visit.to_dict()
        if data.get('date') == today:
            daily_visits += 1

    # Low stock: any medicine below threshold (e.g., 10)
    low_stock = []
    for med in db.collection('medicines').stream():
        m = med.to_dict()
        if m.get('stock', 0) <= 10:
            low_stock.append(m)

    return render_template('admin_dashboard.html', total_patients=total_patients,
                           daily_visits=daily_visits, low_stock=low_stock)


# ================= Run =================
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)

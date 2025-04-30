# Flask TCM POS App — Full Scaffold with Routing, Templates, and Firebase
# This will include inventory, patients, prescriptions, front desk queue, and receipt functionality.

from flask import Flask, render_template, request, redirect, url_for, flash,Response,send_file,jsonify,session,g
from firebase_admin import credentials, firestore, initialize_app, auth
from datetime import datetime
from PIL import Image
import io
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from collections import defaultdict
import requests

app = Flask(__name__)
app.secret_key = 'your-secret-key'

FIREBASE_API_KEY = "AIzaSyBQ7JomtN49PzQcwFJQPb7F4ytySGriTUs"

# Firebase Initialization
cred = credentials.Certificate("lumiere-583de-firebase-adminsdk-fbsvc-1501d71f13.json")
initialize_app(cred)
db = firestore.client()

@app.route('/')
def home():
    return redirect(url_for('patients'))

translations = {
    'en': {
        'add_patient': 'Add Patient',
        'edit_patient': 'Edit Patient',
        'delete_patient': 'Delete Patient',
        'full_name': 'Full Name',
        'nric': 'NRIC / ID',
        'dob': 'Date of Birth',
        'gender': 'Gender',
        'male': 'Male',
        'female': 'Female',
        'contact': 'Contact Number',
        'email': 'Email',
        'address': 'Address',
        'medical_conditions': 'Medical Conditions',
        'diabetes': 'Diabetes',
        'hypertension': 'Hypertension',
        'heart_disease': 'Heart Disease',
        'asthma': 'Asthma',
        'stroke': 'Stroke',
        'kidney_disease': 'Kidney Disease',
        'other_conditions': 'Other Conditions',
        'save_changes': 'Save Changes',
        'yes': 'Yes',
        'no': 'No',
        'cancel': 'Cancel',
        'search': 'Search',
        'inventory': 'Inventory',
        'add_medicine': 'Add Medicine',
        'edit_medicine': 'Edit Medicine',
        'delete_medicine': 'Delete Medicine',
        'barcode': 'Barcode',
        'type': 'Type',
        'price': 'Price',
        'stock': 'Stock',
        'dosage_info': 'Dosage Info',
        'batch_number': 'Batch Number',
        'expiry_date': 'Expiry Date',
        'patients': 'Patients',
        'visits': 'Visits',
        'condition': 'Condition',
        'notes': 'Notes',
        'medicine_name': 'Medicine Name',
        'quantity': 'Quantity',
        'dosage': 'Dosage',
        'actions': 'Actions',
        'confirm_visit': 'Confirm Visit',
        'save_draft': 'Save Draft',
        'no_visit_history': 'No visit history yet.',
        'appointment': 'Appointment',
        'doctor_appointment_calendar': 'Doctor Appointment Calendar',
        'patient_name': 'Patient Name',
        'save_appointments': 'Save Appointments',
        'front_desk': 'Front Desk',
        'waiting': 'Waiting',
        'completed': 'Completed',
        'mark_completed': 'Mark Completed',
        'void': 'Void',
        'receipt': 'Receipt',
        'services_rendered': 'Services Rendered',
        'generate_pdf': 'Generate PDF Receipt',
        'back_to_queue': 'Back to Queue',
        'admin': 'Admin',
        'settings': 'Settings',
        'logout': 'Logout',
        'language_switch': '中文',
        'login': 'Login',
        'email_address': 'Email Address',
        'password': 'Password',
        'submit': 'Submit',
        'dashboard': 'Dashboard',
    },
    'zh': {
        'add_patient': '添加病人',
        'edit_patient': '编辑病人',
        'delete_patient': '删除病人',
        'full_name': '姓名',
        'nric': '身份证/编号',
        'dob': '出生日期',
        'gender': '性别',
        'male': '男',
        'female': '女',
        'contact': '联系电话',
        'email': '电邮',
        'address': '地址',
        'medical_conditions': '病史',
        'other_conditions': '其他病症',
        'diabetes': '糖尿病',
        'hypertension': '高血压',
        'heart_disease': '心脏病',
        'asthma': '哮喘',
        'stroke': '中风',
        'kidney_disease': '肾病',
        'save_changes': '保存更改',
        'yes': '是',
        'no': '否',
        'cancel': '取消',
        'search': '搜索',
        'inventory': '库存',
        'add_medicine': '添加药品',
        'edit_medicine': '编辑药品',
        'delete_medicine': '删除药品',
        'barcode': '条码',
        'type': '类型',
        'price': '价格',
        'stock': '库存',
        'dosage_info': '剂量信息',
        'batch_number': '批号',
        'expiry_date': '有效期',
        'patients': '病人',
        'visits': '就诊记录',
        'condition': '病情',
        'notes': '备注',
        'medicine_name': '药品名称',
        'quantity': '数量',
        'dosage': '剂量',
        'actions': '操作',
        'confirm_visit': '确认就诊',
        'save_draft': '保存草稿',
        'no_visit_history': '暂无就诊记录。',
        'appointment': '预约',
        'doctor_appointment_calendar': '医生预约日历',
        'patient_name': '病人姓名',
        'save_appointments': '保存预约',
        'front_desk': '前台',
        'waiting': '等待中',
        'completed': '已完成',
        'mark_completed': '标记为完成',
        'void': '作废',
        'receipt': '收据',
        'services_rendered': '提供的服务',
        'generate_pdf': '生成 PDF 收据',
        'back_to_queue': '返回队列',
        'admin': '管理员',
        'settings': '设置',
        'logout': '登出',
        'language_switch': 'English',
        'login': '登录',
        'email_address': '邮箱地址',
        'password': '密码',
        'submit': '提交',
        'dashboard': '仪表盘',
    }
}


@app.context_processor
def inject_translation():
    lang = g.get('lang', 'en')
    return {
        't': lambda key: translations[lang].get(key, key)
    }


@app.before_request
def set_language():
    g.lang = session.get('lang', 'en')

@app.route('/switch_language', methods=['POST'])
def switch_language():
    current = session.get('lang', 'en')
    session['lang'] = 'zh' if current == 'en' else 'en'
    next_page = request.form.get('next') or url_for('home')
    return redirect(next_page)

# ================= Inventory =================
@app.route('/api/medicines')
def get_medicine_names():
    meds = db.collection('medicines').stream()
    names = [m.to_dict().get('name', '') for m in meds if m.to_dict().get('name')]
    return {'results': names}

@app.route('/inventory')
def inventory():
    query = request.args.get('q', '').strip().lower()
    medicines_ref = db.collection('medicines')
    all_docs = medicines_ref.stream()

    medicines = []
    for doc in all_docs:
        data = doc.to_dict()
        data['id'] = doc.id  # ✅ Needed for adjusting/editing
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
        data['batch_number'] = request.form.get('batch_number', '')
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



@app.route('/inventory/adjust/<id>/increase', methods=['POST'])
def increase_stock(id):
    ref = db.collection('medicines').document(id)
    doc = ref.get()
    if doc.exists:
        current = doc.to_dict().get('stock', 0)
        ref.update({'stock': current + 1})
        flash('✅ Stock increased by 1.')
    else:
        flash('❌ Medicine not found.')
    return redirect(url_for('inventory'))

@app.route('/inventory/adjust/<id>/set', methods=['POST'])
def set_stock(id):
    new_stock = int(request.form.get('new_stock', 0))
    ref = db.collection('medicines').document(id)
    if new_stock >= 0:
        ref.update({'stock': new_stock})
        flash('✅ Stock updated successfully.')
    else:
        flash('❌ Invalid stock value.')
    return redirect(url_for('inventory'))

@app.route('/inventory/edit/<id>', methods=['GET', 'POST'])
def edit_medicine(id):
    medicine_ref = db.collection('medicines').document(id)
    
    if request.method == 'POST':
        data = request.form.to_dict()
        data['price'] = float(data['price'])
        data['stock'] = int(data['stock'])
        data['batch_number'] = request.form.get('batch_number', '')
        medicine_ref.update(data)
        flash('Medicine updated successfully!')
        return redirect(url_for('inventory'))

    medicine = medicine_ref.get().to_dict()
    if not medicine:
        flash('Medicine not found!')
        return redirect(url_for('inventory'))

    medicine['id'] = id
    return render_template('edit_medicine.html', medicine=medicine)

@app.route('/inventory/delete/<id>', methods=['POST'])
def delete_medicine(id):
    db.collection('medicines').document(id).delete()
    flash('❌ Medicine deleted successfully.')
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
        action = request.form.get('action')

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
            'created_at': datetime.now().isoformat(),
            'status': 'draft' if action == 'save_draft' else 'confirmed'
        }

        # ❗ Always delete existing drafts first
        drafts = patient_ref.collection('visits').where('status', '==', 'draft').stream()
        for d in drafts:
            d.reference.delete()

        # Add new visit
        patient_ref.collection('visits').add(visit)

        if action == 'confirm' and prescribed_meds:
            db.collection('front_desk_queue').add({
                'patient_id': id,
                'items': prescribed_meds,
                'status': 'waiting',
                'timestamp': datetime.now().isoformat()
            })

        flash('Visit saved as draft.' if action == 'save_draft' else 'Visit confirmed and sent to front desk.')
        return redirect(url_for('patient_visits', id=id))

    # ✅ Fetch latest draft if exists
    draft_query = patient_ref.collection('visits').where('status', '==', 'draft').limit(1).stream()
    draft = next(draft_query, None)
    draft = draft.to_dict() if draft else None

    # ✅ Only show confirmed visits
    visits = patient_ref.collection('visits')\
        .where('status', '==', 'confirmed')\
        .order_by('date', direction=firestore.Query.DESCENDING)\
        .stream()
    visits = [{**v.to_dict(), 'id': v.id} for v in visits]

    med_names = [m.to_dict().get('name') for m in db.collection('medicines').stream()]

    return render_template('patient_visits.html', patient=patient, visits=visits, medicine_names=med_names, draft=draft)



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

    # You can predefine available services here:
    services = [
        "Consultation",
        "Acupuncture",
        "Cupping Therapy",
        "Tui Na Massage",
        "Herbal Medicine Advice"
    ]

    return render_template(
        'receipt.html',
        patient=patient,
        items=data['items'],
        total=data['total'],
        services=services  # pass services list to HTML
    )


@app.route('/receipt/queue/<queue_id>')
def queue_receipt(queue_id):
    queue_ref = db.collection('front_desk_queue').document(queue_id)
    queue_data = queue_ref.get().to_dict()

    # ✅ Update status
    queue_ref.update({'status': 'completed'})

    # ✅ Build receipt
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

    # ✅ Define available services here too
    services = [
        "Newly Diagnosed",
        "Acupuncture",
        "Cupping Treatment (per part)",
        "Scrapping Treatment",
        "Pricking Bloodletting",
        "Calf bruise Bloodletting",
        "Bandage",
        "Plaster Cloth",
        "Pain Treatments (per part)",
        "Capsules",
        "Honey Pill (big)",
        "Tablets",
        "Package 1 (Free clinic fee, acupuncture 1X)",
        "Package 2 (Free clinic fee, acupuncture 3X)",
        "Package 3 (Free clinic fee, acupuncture 5X)",
        "Acupuncture & Cupping Package (10X, 1 aching part each time)"
        "Acupuncture Package (10x)",
        "Acupuncture Package (20x)",
        "Acupuncture Package (30x)",
        "Cupping (10x)",
        "Massage Package (10x each 45 mins)",
        "Facial Acupuncture & Beauty Massage (15 minutes)",
        "Facial Beauty Acupuncture",
        "Facial Beauty Scraping",
        "Beauty Acupuncture Package (10x)",
        "Beauty Acupoint Package (10x)",
        "Weight Loss Partial Body Massage 30 mins",
        "Weight Loss Whole Body Massage 60 mins",
        "Weight Loss Acupuncture",
        "Abdominal Cupping Weight Loss",
        "Thigh, Hips ( Bilateral ) Cupping Weight Loss",
        "Loss Weight Acupuncture Package (10x)",
        "Acupuncture 10X, Abdominal Cupping 10X, Free Clinic Fee",
        "Acupuncture 10X + Thigh, Hips (Bilateral) ,Abdominal Cupping 10X, Free Clinic Fee"
    ]

    return render_template(
        'reciepts.html',
        patient=patient,
        items=items,
        total=round(total, 2),
        services=services   # 🛠️ PASS SERVICES HERE
    )

@app.route('/generate_receipt_pdf', methods=['POST'])
def generate_receipt_pdf():
    patient_name = request.form.get('patient_name', 'Patient')
    visit_date = datetime.now().strftime("%d-%m-%Y")
    bill_no = f"{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Medicines
    medicine_count = int(request.form.get('medicine_count', 0))
    prescribed_medicines = []
    medicine_total = 0
    for i in range(1, medicine_count + 1):
        name = request.form.get(f'medicine_name_{i}')
        price = float(request.form.get(f'medicine_price_{i}', 0))
        qty = int(request.form.get(f'medicine_qty_{i}', 0))
        subtotal = price * qty
        prescribed_medicines.append((name, qty, price, subtotal))
        medicine_total += subtotal

    # Services
    services = []
    service_total = 0
    for key in request.form.keys():
        if key.startswith('service_'):
            service_name = request.form[key]
            index = key.split('_')[1]
            amount = float(request.form.get(f'amount_{index}', 0))
            if request.form.get(f'use_{index}'):
                services.append((service_name, amount))
                service_total += amount

    grand_total = medicine_total + service_total

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Header
    p.setFont("Helvetica-Bold", 16)
    p.drawCentredString(width/2, height - 40, "春秋堂中医药诊所")
    p.setFont("Helvetica-Bold", 14)
    p.drawCentredString(width/2, height - 60, "Harmony TCM Healthcare")
    p.setFont("Helvetica", 9)
    p.drawCentredString(width/2, height - 75, "Reg. No: 201223383")
    p.setFont("Helvetica", 10)
    p.drawCentredString(width/2, height - 90, "Blk 412 Bedok North Ave 2 #01-142 Singapore 460412    Tel: 9072 1288")

    p.setFont("Helvetica-Bold", 18)
    p.drawCentredString(width/2, height - 120, "Receipt")

    p.setFont("Helvetica", 12)
    p.drawRightString(width - 50, height - 140, f"No. {bill_no[-5:]}")

    y = height - 170
    p.setFont("Helvetica", 11)
    p.drawString(50, y, f"To: {patient_name}")
    p.drawString(50, y - 15, f"Visit Date: {visit_date}")
    p.drawString(50, y - 30, f"Bill No.: {bill_no}")

    y -= 70
    row_height = 20
    table_left = 50
    table_right = width - 50
    total_rows = len(prescribed_medicines) + len(services) + 2
    table_height = total_rows * row_height

    table_top = y
    table_bottom = y - table_height

    p.setFont("Helvetica", 10)
    p.rect(table_left, table_bottom, table_right - table_left, table_height)

    p.setFont("Helvetica-Bold", 11)
    p.line(table_left, table_top - row_height, table_right, table_top - row_height)
    p.drawString(table_left + 10, table_top - 15, "Services Rendered")
    p.drawRightString(table_right - 10, table_top - 15, "Amount (S$)")

    y_cursor = table_top - row_height

    p.setFont("Helvetica", 10)
    for name, qty, price, subtotal in prescribed_medicines:
        y_cursor -= row_height
        p.line(table_left, y_cursor, table_right, y_cursor)
        p.drawString(table_left + 10, y_cursor + 5, f"{name} ({qty}x @ ${price:.2f})")
        p.drawRightString(table_right - 10, y_cursor + 5, f"{subtotal:.2f}")

    for name, amount in services:
        y_cursor -= row_height
        p.line(table_left, y_cursor, table_right, y_cursor)
        p.drawString(table_left + 10, y_cursor + 5, name)
        p.drawRightString(table_right - 10, y_cursor + 5, f"{amount:.2f}")

    y_cursor -= row_height
    p.line(table_left, y_cursor, table_right, y_cursor)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(table_left + 10, y_cursor + 5, "Total")
    p.drawRightString(table_right - 10, y_cursor + 5, f"{grand_total:.2f}")

    p.line(60, 60, 160, 60)
    p.drawString(80, 45, "Date")
    p.line(width - 200, 60, width - 100, 60)
    p.drawString(width - 180, 45, "Physician's Signature")

    p.showPage()
    p.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"Receipt_{bill_no}.pdf", mimetype='application/pdf')



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
    items = queue_doc.get('items', [])
    current_status = queue_doc.get('status')

    if status == 'completed':
        # ✅ Decrement stock when marking as completed
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

    elif status == 'void':
        # ✅ Revert stock if voiding a completed order
        if current_status == 'completed':
            for med in items:
                query = db.collection('medicines').where('name', '==', med['name']).limit(1).stream()
                found = next(query, None)
                if found:
                    ref = db.collection('medicines').document(found.id)
                    med_doc = found.to_dict()
                    new_stock = med_doc.get('stock', 0) + int(med['quantity'])
                    ref.update({'stock': new_stock})

        queue_ref.update({'status': 'waiting'})
        return redirect(url_for('front_desk'))

    # 🟡 Just update status if not completed or void
    queue_ref.update({'status': status})
    return redirect(url_for('front_desk'))

# ================= dashboard =================
@app.route('/admin/dashboard')
def admin_dashboard():
    today = datetime.now().date().isoformat()

    # Patient count
    total_patients = len(list(db.collection('patients').stream()))

    # Visits today
    visits_today = []
    visits_ref = db.collection_group('visits').stream()
    for v in visits_ref:
        data = v.to_dict()
        if data.get('date') == today:
            patient_id = v.reference.parent.parent.id
            patient = db.collection('patients').document(patient_id).get().to_dict()
            visits_today.append({
                'patient': patient['name'] if patient else 'Unknown',
                'condition': data.get('condition'),
                'date': data.get('date')
            })

    # Prescriptions count
    total_prescriptions = len(list(db.collection('prescriptions').stream()))

    # Low stock medicines
    low_stock = []
    for m in db.collection('medicines').stream():
        data = m.to_dict()
        if data.get('stock', 0) <= 10:
            low_stock.append(data)

    # Recent completed queue items
    completed_queue = db.collection('front_desk_queue')\
        .where('status', '==', 'completed')\
        .order_by('timestamp', direction=firestore.Query.DESCENDING).limit(5).stream()

    recent_completed = []
    for item in completed_queue:
        doc = item.to_dict()
        pid = doc.get('patient_id')
        patient = db.collection('patients').document(pid).get().to_dict()
        recent_completed.append({
            'patient_name': patient['name'] if patient else 'Unknown',
            'status': doc['status'],
            'items': doc.get('items', []),
            'timestamp': doc.get('timestamp', '')
        })

    return render_template("admin_dashboard.html",
        total_patients=total_patients,
        daily_visits=len(visits_today),
        total_prescriptions=total_prescriptions,
        low_stock=low_stock,
        today_visits=visits_today,
        recent_completed=recent_completed
    )

@app.route('/admin/export/visits.csv')
def export_visits_csv():
    all_visits = []
    patients = db.collection('patients').stream()

    for p in patients:
        pdata = p.to_dict()
        visits = db.collection('patients').document(p.id).collection('visits').stream()
        for v in visits:
            vdata = v.to_dict()
            all_visits.append({
                'Patient Name': pdata.get('name'),
                'NRIC': pdata.get('nric'),
                'Date': vdata.get('date'),
                'Condition': vdata.get('condition'),
                'Notes': vdata.get('notes'),
                'Created At': vdata.get('created_at')
            })

    df = pd.DataFrame(all_visits)
    csv_data = df.to_csv(index=False)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=visit_records.csv"}
    )

@app.route('/admin/export/queue.csv')
def export_queue_csv():
    queue_data = []
    queue = db.collection('front_desk_queue').stream()
    for q in queue:
        qdata = q.to_dict()
        patient = db.collection('patients').document(qdata.get('patient_id')).get().to_dict()
        queue_data.append({
            'Patient Name': patient['name'] if patient else 'Unknown',
            'Status': qdata.get('status'),
            'Timestamp': qdata.get('timestamp'),
            'Items': "; ".join([f"{i['quantity']}x {i['name']}" for i in qdata.get('items', [])])
        })

    df = pd.DataFrame(queue_data)
    csv_data = df.to_csv(index=False)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=queue_log.csv"}
    )

# =================== Appointment ===================
@app.route('/appointments')
def appointments_combined():
    date_str = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')

    # Load bookings for selected date
    appointment_docs = db.collection('appointments').where('date', '==', date_str).stream()
    patients = []
    appointment_data = {}
    for doc in appointment_docs:
        data = doc.to_dict()
        name = data['patient_name']
        contact = data.get('contact', '')
        patients.append({'name': name, 'contact': contact})
        appointment_data[name] = data.get('slots', {})

    # Count bookings per day for calendar coloring
    all_docs = db.collection('appointments').stream()
    booking_counts = defaultdict(int)
    for doc in all_docs:
        data = doc.to_dict()
        if 'date' in data:
            booking_counts[data['date']] += 1

    event_list = []
    for date, count in booking_counts.items():
        color = "#198754" if count <= 2 else "#ffc107" if count <= 5 else "#dc3545"
        event_list.append({
            'title': f"{count} bookings",
            'start': date,
            'allDay': True,
            'backgroundColor': color,
            'borderColor': color
        })

    return render_template('appointments.html',
                           patients=patients,
                           appointments=appointment_data,
                           selected_date=date_str,
                           events=event_list)

@app.route('/appointments/save', methods=['POST'])
def save_appointments():
    form = request.form.to_dict()
    date_str = form.get('date') or datetime.now().strftime('%Y-%m-%d')

    appointment_batches = []
    row_num = 1
    while f"patient_name_{row_num}" in form:
        patient_name = form.get(f"patient_name_{row_num}")
        contact = form.get(f"contact_{row_num}", "")
        slots = {}
        for hour in range(9, 18):
            slot_value = form.get(f"slot_{row_num}_{hour}", "")
            slots[str(hour)] = slot_value

        appointment_batches.append({
            'patient_name': patient_name,
            'contact': contact,
            'slots': slots,
            'date': date_str,
            'timestamp': datetime.now().isoformat()
        })
        row_num += 1

    for doc in db.collection('appointments').where('date', '==', date_str).stream():
        doc.reference.delete()

    for batch in appointment_batches:
        db.collection('appointments').add(batch)

    flash(f"Appointments saved for {date_str}")
    return redirect(url_for('appointments_combined', date=date_str))


@app.route('/appointments/json')
def appointments_json():
    date_str = request.args.get('date')
    if not date_str:
        return {'patients': []}

    appointment_docs = db.collection('appointments').where('date', '==', date_str).stream()
    result = []
    for doc in appointment_docs:
        data = doc.to_dict()
        result.append({
            'name': data.get('patient_name'),
            'contact': data.get('contact', ''),
            'slots': data.get('slots', {})
        })
    return {'patients': result}

@app.route('/appointments/delete', methods=['POST'])
def delete_appointment():
    patient_name = request.form.get('patient_name')
    date = request.form.get('date')

    # Find and delete matching appointment
    docs = db.collection('appointments') \
        .where('patient_name', '==', patient_name) \
        .where('date', '==', date).stream()

    for doc in docs:
        doc.reference.delete()

    return '', 204  # No content for JS

@app.route('/appointments/event_counts')
def appointment_event_counts():
    booking_counts = defaultdict(int)

    all_docs = db.collection('appointments').stream()
    for doc in all_docs:
        data = doc.to_dict()
        date = data.get('date')
        if date:
            booking_counts[date] += 1

    events = []
    for date, count in booking_counts.items():
        color = "#198754" if count <= 2 else "#ffc107" if count <= 5 else "#dc3545"
        events.append({
            'title': f"{count} bookings",
            'start': date,
            'allDay': True,
            'backgroundColor': color,
            'borderColor': color
        })

    return jsonify(events)

# =================== Login ===================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        try:
            # Use Firebase REST API to verify email/password
            payload = {
                'email': email,
                'password': password,
                'returnSecureToken': True
            }
            r = requests.post(
                f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}",
                json=payload
            )
            res = r.json()
            if "idToken" in res:
                session['user'] = res['localId']
                flash("✅ Login successful.")
                return redirect(url_for('patients'))
            else:
                flash("❌ Invalid credentials.")
        except Exception as e:
            flash(f"❌ Error: {str(e)}")
    return render_template('login.html')

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))

    if request.method == 'POST':
        uid = session['user']
        new_email = request.form.get('new_email')
        new_password = request.form.get('new_password')

        updates = {}
        if new_email:
            updates['email'] = new_email
        if new_password:
            updates['password'] = new_password

        try:
            auth.update_user(uid, **updates)
            flash("✅ Account updated successfully.")
        except Exception as e:
            flash(f"❌ Error: {str(e)}")

    return render_template('settings.html')


@app.before_request
def check_auth():
    # Allow access to login page and static files without login
    allowed_routes = ['login']  
    if request.endpoint not in allowed_routes and 'user' not in session:
        return redirect(url_for('login'))


# ================= Run =================
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)

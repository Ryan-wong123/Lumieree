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
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib import colors
from collections import defaultdict
import requests
import re
import csv
import uuid
from werkzeug.utils import secure_filename
import click

app = Flask(__name__)
app.secret_key = 'your-secret-key'

FIREBASE_API_KEY = "AIzaSyBQ7JomtN49PzQcwFJQPb7F4ytySGriTUs"

# Firebase Initialization
cred = credentials.Certificate("lumiere-583de-firebase-adminsdk-fbsvc-1501d71f13.json")
initialize_app(cred)
db = firestore.client()

# --- Multi-tenant helpers ---
def current_uid():
    return session.get('user')

def require_login():
    if 'user' not in session:
        return redirect(url_for('login'))

def with_owner(query):
    """Attach owner filter to a top-level collection/collection group query."""
    return query.where('owner_id', '==', current_uid())

@app.route('/')
def home():
    return redirect(url_for('patients'))
# Global service catalog (backend source of truth)
SERVICE_CATALOG = [
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
    "Acupuncture & Cupping Package (10X, 1 aching part each time)",
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
    "Weight Loss Acupuncture Package (10x)",
    "Acupuncture 10X, Abdominal Cupping 10X, Free Clinic Fee",
    "Acupuncture 10X + Thigh, Hips (Bilateral) ,Abdominal Cupping 10X, Free Clinic Fee",
]

translations = {
    'en': {
        'add_patient': 'Add Patient',
        'edit_patient': 'Edit Patient',
        'confirm_delete_patient': 'Are you sure you want to delete this patient?',
        'delete_patient': 'Delete Patient',
        'search_patient_placeholder': 'Search by name or contact...',
        'no_patients_found': 'No patients found.',
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
        'other_conditions': 'Other Conditions',
        'diabetes': 'Diabetes',
        'hypertension': 'Hypertension',
        'heart_disease': 'Heart Disease',
        'asthma': 'Asthma',
        'stroke': 'Stroke',
        'kidney_disease': 'Kidney Disease',
        'High Cholesterol': 'High Cholesterol',
        'save_changes': 'Save Changes',
        'yes': 'Yes',
        'no': 'No',
        'cancel': 'Cancel',
        'search': 'Search',
        'inventory': 'Inventory',
        'add_medicine': 'Add Medicine',
        'edit_medicine': 'Edit Medicine',
        'confirm_delete_medicine': 'Are you sure you want to delete this medicine? This action cannot be undone.',
        'delete_medicine': 'Delete Medicine',
        'inventory_management': 'Inventory Management',
        'search_placeholder': 'Search by name or barcode...',
        'scan': 'Scan',
        'stop_scanning': 'Stop Scanning',
        'barcode': 'Barcode',
        'type': 'Type',
        'price': 'Selling Price',
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
        'edit': 'Edit',
        'confirm_visit': 'Confirm Visit',
        'save_draft': 'Save Draft',
        'add_new_visit': 'Add New Visit',
        'no_visit_history': 'No visit history yet.',
        'condition_placeholder': "Describe patient's condition...",
        'prescribed_meds': 'Prescribed Medications',
        'appointment': 'Appointment',
        'overall_notes': 'Overall Notes',
        'notes_placeholder': 'Visit notes...',
        'past_visits': 'Past Visits',
        'date': 'Date',
        'medications': 'Medications',
        'doctor_appointment_calendar': 'Doctor Appointment Calendar',
        'patient_name': 'Patient Name',
        'appointments': 'appointments',
        'save_appointments': 'Save Appointments',
        'front_desk': 'Front Desk',
        'front_desk_queue': 'Front Desk Prescription Queue',
        'waiting': 'Waiting',
        'completed': 'Completed',
        'status': 'Status',
        'mark_completed': 'Mark Completed',
        'void': 'Void',
        'no_waiting_items': 'No waiting items.',
        'no_completed_items': 'No completed items.',
        'deleted': 'Deleted',
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
        'receipt_for': 'Receipt for',
        'medicine': 'Medicine',
        'unit_price': 'Unit Price ($)', 'subtotal': 'Subtotal ($)',
        'subtotal': 'Subtotal ($)',
        'subtotal_meds': 'Subtotal (Medicines):',
        'use': 'Use',
        'service': 'Service',
        'grand_total': 'Grand Total:',
        'account_settings': 'Account Settings',
        'new_email': 'New Email',
        'new_password': 'New Password',
        'update_account': 'Update Account',
        'admin_dashboard': 'Admin Dashboard',
        'total_patients': 'Total Patients',
        'visits_today': 'Visits Today',
        'prescriptions_created': 'Prescriptions Created',
        'low_stock_medicines': 'Low Stock Medicines',
        'stock_healthy': 'All stock levels are healthy ✅',
        'no_visits_today': 'No visits logged today.',
        'recent_completed_orders': 'Recently Completed Orders',
        'items': 'Items',
        'time': 'Time',
        'no_completed_orders': 'No completed items in queue.',
        'export_visits_csv': 'Export Visits CSV',
        'export_prescriptions_csv': 'Export Prescriptions CSV',
        'taking_western_medicine': 'Taking Western Medicine',
        'western_medicine_duration': 'How long taking Western Medicine',
        'drug_allergies': 'Drug Allergies',
        'discharge_advice': 'Discharge Advice',
        'discharge_advice_placeholder': 'Key instructions for aftercare, red flags, lifestyle or diet advice…',
        'select_unit': 'Select unit',
        'pills': 'pills',
        'grams': 'grams',
        'bottle': 'bottle',
        'company': 'Company',
        'importcsv': 'Import CSV',
        'apply': 'Apply',
        'reset': 'Reset',
        'super admin': 'Super Admin',
        'create_new_user': 'Create New User',
        'user': 'User',
        'role': 'Role',
        'active': 'Active',
        'created_by': 'Created By',
        'staff': 'Staff',
        'admin': 'Admin',
        'back': 'Back',
        'edit_user': 'Edit User',
        'change_email': 'Change Email',
        'change_password': 'Change Password',
        'other_charges': 'Other Charges',
        'description': 'Description',
        'eg_adminfee': 'e.g. Admin fee',
        'physician_name': "Physician's Name",
        'physician_password': "Physician's Password",
        'subtotal_services': 'Subtotal (Services):',
    },
    'zh': {
        'add_patient': '添加病人',
        'edit_patient': '编辑病人',
        'confirm_delete_patient': '确定要删除该病人吗？',
        'delete_patient': '删除病人',
        'search_patient_placeholder': '按姓名或联系方式搜索...',
        'no_patients_found': '未找到病人记录。',
        'full_name': '姓名',
        'nric': '身份证号码',
        'dob': '出生日期',
        'gender': '性别',
        'male': '男',
        'female': '女',
        'contact': '联系电话',
        'email': '电子邮箱',
        'address': '地址',
        'medical_conditions': '既往病史',
        'other_conditions': '其他疾病',
        'diabetes': '糖尿病',
        'hypertension': '高血压',
        'heart_disease': '心脏病',
        'asthma': '哮喘',
        'stroke': '中风',
        'kidney_disease': '肾病',
        'High Cholesterol': '高胆固醇',
        'save_changes': '保存更改',
        'yes': '是',
        'no': '否',
        'cancel': '取消',
        'search': '搜索',
        'inventory': '库存',
        'add_medicine': '添加药品',
        'edit_medicine': '药品内容增减',
        'confirm_delete_medicine': '您确定要删除此药品吗？此操作无法撤销。',
        'delete_medicine': '删除药品',
        'inventory_management': '药品库存管理',
        'search_placeholder': '按名称或条形码搜索...',
        'scan': '扫描',
        'stop_scanning': '停止扫描',
        'barcode': '条形码',
        'type': '类型',
        'price': '卖价格',
        'stock': '库存',
        'dosage_info': '剂量信息',
        'batch_number': '批号',
        'expiry_date': '有效期',
        'patients': '患者',
        'visits': '就诊次数',
        'condition': '病情',
        'notes': '备注',
        'medicine_name': '药品名',
        'quantity': '数量',
        'dosage': '剂量',
        'actions': '操作',
        'edit': '编辑',
        'confirm_visit': '确认就诊',
        'save_draft': '保存草稿',
        'add_new_visit': '添加新就诊',
        'no_visit_history': '暂无就诊记录。',
        'condition_placeholder': '描述患者病情...',
        'prescribed_meds': '处方药物计价',
        'appointment': '预约',
        'overall_notes': '总体备注',
        'notes_placeholder': '就诊备注...',
        'past_visits': '既往就诊',
        'date': '日期',
        'medications': '药物',
        'doctor_appointment_calendar': '医生预约日历',
        'patient_name': '患者姓名',
        'appointments': '预约',
        'save_appointments': '保存预约',
        'front_desk': '前台',
        'front_desk_queue': '前台处方队列',
        'waiting': '等待中',
        'completed': '已完成',
        'status': '状态',
        'mark_completed': '标记为已完成',
        'void': '作废',
        'no_waiting_items': '无等待中项目。',
        'no_completed_items': '无已完成项目。',
        'deleted': '已删除',
        'receipt': '收据',
        'services_rendered': '已治疗项目',
        'generate_pdf': '生成 PDF 收据',
        'back_to_queue': '返回队列',
        'admin': '管理员',
        'settings': '设置',
        'logout': '注销',
        'language_switch': 'English',
        'login': '登录',
        'email_address': '邮箱地址',
        'password': '密码',
        'submit': '提交',
        'dashboard': '仪表盘',
        'receipt_for': '收据 - ',
        'medicine': '药品',
        'unit_price': '单价（$）',
        'subtotal': '小计（$）',
        'subtotal_meds': '药品小计：',
        'use': '使用',
        'service': '治疗项目名称',
        'grand_total': '总计：',
        'account_settings': '账户设置',
        'new_email': '新电子邮件',
        'new_password': '新密码',
        'update_account': '更新账户',
        'admin_dashboard': '管理员仪表盘',
        'total_patients': '病人总数',
        'visits_today': '今日就诊',
        'prescriptions_created': '已创建处方',
        'low_stock_medicines': '库存不足药品',
        'stock_healthy': '库存充足 ✅',
        'no_visits_today': '今天没有就诊记录。',
        'recent_completed_orders': '最近完成的订单',
        'items': '项目',
        'time': '时间',
        'no_completed_orders': '队列中暂无完成项目。',
        'export_visits_csv': '导出就诊病案 CSV',
        'export_prescriptions_csv': '导出处方 CSV',
        'taking_western_medicine': '是否服用西药',
        'western_medicine_duration': '服用西药多久',
        'drug_allergies': '药物过敏',
        'discharge_advice': '出院指导',
        'discharge_advice_placeholder': '出院后的注意事项、警示症状、生活方式或饮食建议…',
        'select_unit': '选择单位',
        'pills': '颗',
        'grams': '克',
        'bottle': '瓶',
        'company': '公司',
        'importcsv': '导入CSV',
        'apply': '应用',
        'reset': '重置',
        'super_admin': '超级管理员',
        'create_new_user': '创建新用户',
        'user': '用户',
        'role': '角色',
        'active': '活跃',
        'created_by': '创建者',
        'staff': '员工',
        'admin': '管理员',
        'back': '返回',
        'edit_user': '编辑用户',
        'change_email': '更改电子邮件',
        'change_password': '更改密码',
        'other_charges': '另外收费',
        'description': '内容',
        'eg_adminfee': '例如',
        'physician_name': '医生姓名',
        'physician_password': '医生密码',
        'subtotal_services': '治疗项目小计：',
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

def normalize_expiry_to_iso(s: str) -> str:
    """
    Accepts:
      - 'YYYY-MM-DD' (returns same)
      - 'DD/MM/YYYY' or 'D/M/YYYY' (converts)
      - 'YYYY-MM-DDTHH:MM:SS...' (cuts to date)
    Returns '' if cannot parse.
    """
    if not s:
        return ""
    s = str(s).strip()

    # Already ISO date (or ISO datetime)
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s[:10]

    # DD/MM/YYYY or D/M/YYYY
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{int(mm):02d}-{int(dd):02d}"

    return ""

@app.route('/api/medicines')
def get_medicine_names():
    require_login()
    meds = with_owner(db.collection('medicines')).stream()
    names = [m.to_dict().get('name', '') for m in meds if m.to_dict().get('name')]
    return {'results': names}

@app.route('/inventory')
def inventory():
    require_login()
    query = request.args.get('q', '').strip().lower()

    medicines_ref = with_owner(db.collection('medicines'))
    all_docs = medicines_ref.stream()

    medicines = []
    for doc in all_docs:
        data = doc.to_dict()
        data['id'] = doc.id  # needed for adjusting/editing
        text_haystack = " ".join([
            data.get('name', ''),
            str(data.get('barcode', ''))  # still searchable if you kept barcodes historically
        ]).lower()
        if query:
            if query in text_haystack:
                medicines.append(data)
        else:
            medicines.append(data)

    return render_template('inventory.html', medicines=medicines)

@app.route('/inventory/add', methods=['GET', 'POST'])
def add_medicine():
    require_login()
    if request.method == 'POST':
        data = request.form.to_dict()
        data['price'] = float(data['price'])
        data['stock'] = int(data['stock'])
        data['expiry_date'] = data['expiry_date']
        data['owner_id'] = current_uid()               # ✅ tenant tag
        db.collection('medicines').add(data)
        flash('Medicine added successfully!')
        return redirect(url_for('inventory'))
    return render_template('add_medicine.html')

@app.route('/inventory/scan-combined', methods=['POST'])
def scan_combined():
    require_login()
    manual_barcode = request.form.get('manual_barcode', '').strip()
    barcode = manual_barcode

    if not barcode:
        flash("❌ No barcode provided.")
        return redirect(url_for('inventory'))

    # quantity
    try:
        amount = int(request.form.get('adjust_amount', 1))
        if amount < 1:
            raise ValueError
    except ValueError:
        flash("❌ Invalid quantity.")
        return redirect(url_for('inventory'))

    adjust_type = request.form.get('adjust_type', 'increase')

    # Find medicine by barcode within tenant
    med_query = with_owner(db.collection('medicines')).where('barcode', '==', barcode).limit(1).stream()
    med = next(med_query, None)

    if not med:
        flash(f"❌ Medicine with barcode {barcode} not found.")
        return redirect(url_for('inventory'))

    doc = med.to_dict()
    current_stock = doc.get('stock', 0)
    new_stock = max(current_stock - amount, 0) if adjust_type == 'decrease' else current_stock + amount
    db.collection('medicines').document(med.id).update({'stock': new_stock})

    flash(f"✅ Stock {'decreased' if adjust_type == 'decrease' else 'increased'} by {amount}. New stock: {new_stock}")
    return redirect(url_for('inventory'))
@app.route('/inventory/adjust/<id>/increase', methods=['POST'])
def increase_stock(id):
    require_login()
    ref = db.collection('medicines').document(id)
    snap = ref.get()
    if snap.exists and snap.to_dict().get('owner_id') == current_uid():
        current = snap.to_dict().get('stock', 0)
        ref.update({'stock': current + 1})
        flash('✅ Stock increased by 1.')
    else:
        flash('❌ Medicine not found.')
    return redirect(url_for('inventory'))

@app.route('/inventory/adjust/<id>/set', methods=['POST'])
def set_stock(id):
    require_login()
    ref = db.collection('medicines').document(id)
    snap = ref.get()
    if not (snap.exists and snap.to_dict().get('owner_id') == current_uid()):
        flash('❌ Medicine not found.')
        return redirect(url_for('inventory'))

    try:
        new_stock = int(request.form.get('new_stock', 0))
        if new_stock < 0:
            raise ValueError
    except ValueError:
        flash('❌ Invalid stock value.')
        return redirect(url_for('inventory'))

    ref.update({'stock': new_stock})
    flash('✅ Stock updated successfully.')
    return redirect(url_for('inventory'))
@app.route('/inventory/edit/<id>', methods=['GET', 'POST'])

@app.route('/inventory/edit/<id>', methods=['GET', 'POST'])
def edit_medicine(id):
    require_login()
    ref = db.collection('medicines').document(id)
    snap = ref.get()
    if not (snap.exists and snap.to_dict().get('owner_id') == current_uid()):
        flash('❌ Medicine not found.')
        return redirect(url_for('inventory'))

    if request.method == 'POST':
        data = request.form.to_dict()
        data['price'] = float(data['price'])
        data['stock'] = int(data['stock'])

        # ✅ Ensure we store ISO format from the date input
        data['expiry_date'] = normalize_expiry_to_iso(data.get('expiry_date', ''))

        ref.update(data)
        flash('Medicine updated successfully!')
        return redirect(url_for('inventory'))

    medicine = snap.to_dict()
    medicine['expiry_date'] = normalize_expiry_to_iso(medicine.get('expiry_date', ''))
    medicine['id'] = id

    #Default dropdown options (your base code)
    DEFAULT_TYPES = ["Powder", "Pill", "Patch"]

    types = set(DEFAULT_TYPES)

    # Add any extra types found in DB
    for m in with_owner(db.collection('medicines')).stream():
        t = (m.to_dict().get('type') or '').strip()
        if t:
            types.add(t)

    types = sorted(types)


    return render_template(
        'edit_medicine.html',
        medicine=medicine,
        medicine_types=types   
    )



@app.route('/inventory/delete/<id>', methods=['POST'])
def delete_medicine(id):
    require_login()
    ref = db.collection('medicines').document(id)
    snap = ref.get()
    if snap.exists and snap.to_dict().get('owner_id') == current_uid():
        ref.delete()
        flash('❌ Medicine deleted successfully.')
    else:
        flash('❌ Medicine not found.')
    return redirect(url_for('inventory'))


# ================= Patients =================
@app.route('/patients')
def patients():
    require_login()
    query = request.args.get('q', '').strip().lower()
    patient_stream = with_owner(db.collection('patients')).stream()

    patients = []
    for p in patient_stream:
        data = p.to_dict()
        data['id'] = p.id
        # visits count (only this user’s tagged visits — see visit tagging below)
        visits = db.collection('patients').document(p.id).collection('visits')\
            .where('owner_id', '==', current_uid())\
            .stream()
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
    require_login()
    if request.method == 'POST':
        data = request.form.to_dict()
        data['created_at'] = datetime.now().isoformat()
        data['last_visit'] = datetime.now().isoformat()
        data['owner_id'] = current_uid()               # ✅ tenant tag
        db.collection('patients').add(data)
        flash('Patient added!')
        return redirect(url_for('patients'))
    return render_template('add_patient.html')

@app.route('/patients/edit/<id>', methods=['GET', 'POST'])
def edit_patient(id):
    require_login()
    ref = db.collection('patients').document(id)
    snap = ref.get()

    if not (snap.exists and snap.to_dict().get('owner_id') == current_uid()):
        flash('❌ Patient not found.')
        return redirect(url_for('patients'))

    if request.method == 'POST':
        data = request.form.to_dict()
        data['updated_at'] = datetime.now().isoformat()
        ref.update(data)
        flash('Patient updated successfully!')
        return redirect(url_for('patients'))

    patient = snap.to_dict()
    patient['id'] = id
    return render_template('edit_patient.html', patient=patient)
@app.route('/patients/<id>/visits', methods=['GET', 'POST'])
def patient_visits(id):
    require_login()
    patient_ref = db.collection('patients').document(id)
    snap = patient_ref.get()
    if not (snap.exists and snap.to_dict().get('owner_id') == current_uid()):
        flash('❌ Patient not found.')
        return redirect(url_for('patients'))
    patient = snap.to_dict()

    # ---------- POST: save visit (meds + services) ----------
    if request.method == 'POST':
        action = request.form.get('action')

        # Prescribed meds (existing behaviour)
        names = request.form.getlist('med_name')
        quantities = request.form.getlist('med_quantity')
        dosages = request.form.getlist('med_dosage')
        prescribed_meds = []
        for n, q, d in zip(names, quantities, dosages):
            if not n:
                continue
            try:
                qv = int(q)
            except Exception:
                qv = 1
            prescribed_meds.append({'name': n, 'quantity': qv, 'dosage': d})

        # ✅ Services (parsed on backend)
        service_names   = request.form.getlist('service_name')     # multiple same-name fields
        service_amounts = request.form.getlist('service_amount')
        services = []
        for name, amt in zip(service_names, service_amounts):
            n = (name or "").strip()
            if not n:
                continue
            try:
                value = float(amt or 0)
            except ValueError:
                value = 0.0
            services.append({'name': n, 'amount': value})

        visit = {
            'date': request.form.get('date') or datetime.now().date().isoformat(),
            'condition': request.form.get('condition'),
            'notes': request.form.get('notes'),
            'discharge_advice': request.form.get('discharge_advice'),
            'prescribed_meds': prescribed_meds,
            'services': services,                     # ✅ save services on the visit
            'created_at': datetime.now().isoformat(),
            'status': 'draft' if action == 'save_draft' else 'confirmed',
            'owner_id': current_uid(),
        }

        # Remove prior drafts for this user under this patient (keeps your behaviour)
        drafts = (patient_ref.collection('visits')
                  .where('owner_id', '==', current_uid())
                  .where('status', '==', 'draft')
                  .stream())
        for d in drafts:
            d.reference.delete()

        # Save visit
        add_res = patient_ref.collection('visits').add(visit)
        visit_id = add_res[1].id

        # Optionally enqueue to front desk with a pointer to the visit (helps receipts)
        if action == 'confirm' and prescribed_meds:
            db.collection('front_desk_queue').add({
                'patient_id': id,
                'visit_id': visit_id,                 # ✅ carry visit_id
                'items': prescribed_meds,
                'status': 'waiting',
                'timestamp': datetime.now().isoformat(),
                'owner_id': current_uid(),
            })

        flash('Visit saved as draft.' if action == 'save_draft' else 'Visit confirmed and sent to front desk.')
        return redirect(url_for('patient_visits', id=id))

    # ---------- GET: render page ----------
    # build past visits list
    visits_q = (patient_ref.collection('visits')
                .where('owner_id', '==', current_uid())
                .order_by('date')
                .stream())
    visits = [dict(v.to_dict() | {'id': v.id}) for v in visits_q]

    # optional: a draft to prefill (if you keep drafts)
    draft = None


    # Medicine names + price map for dynamic pricing
    med_names = []
    medicine_price_map = {}

    for m in with_owner(db.collection('medicines')).stream():
        d = m.to_dict()
        name = d.get('name')
        if not name:
            continue
        med_names.append(name)
        try:
            price = float(d.get('price', 0) or 0)
        except (TypeError, ValueError):
            price = 0.0
        medicine_price_map[name] = price

    return render_template(
        'patient_visits.html',
        patient=patient,
        visits=visits,
        draft=draft,
        medicine_names=med_names,
        medicine_price_map=medicine_price_map,  # 🔹 new
        service_catalog=SERVICE_CATALOG,        # ✅ existing
    )


@app.route('/patients/delete/<id>', methods=['POST'])
def delete_patient(id):
    require_login()
    ref = db.collection('patients').document(id)
    snap = ref.get()

    if not (snap.exists and snap.to_dict().get('owner_id') == current_uid()):
        flash('❌ Patient not found.')
        return redirect(url_for('patients'))

    # Delete visits (only those owned by the user)
    visits = ref.collection('visits').where('owner_id', '==', current_uid()).stream()
    for v in visits:
        v.reference.delete()

    ref.delete()
    flash('✅ Patient and their visit records deleted.')
    return redirect(url_for('patients'))

@app.context_processor
def inject_now():
    return { 'now': datetime.now }


# ================= Prescriptions =================
@app.route('/prescriptions/create', methods=['GET', 'POST'])
def create_prescription():
    require_login()
    if request.method == 'POST':
        patient_id = request.form['patient_id']
        # Verify patient belongs to owner
        p_snap = db.collection('patients').document(patient_id).get()
        if not (p_snap.exists and p_snap.to_dict().get('owner_id') == current_uid()):
            flash('❌ Invalid patient.')
            return redirect(url_for('create_prescription'))

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
            'timestamp': datetime.now().isoformat(),
            'sent_to_front_desk': True,
            'owner_id': current_uid()     # ✅
        })
        db.collection('front_desk_queue').add({
            'prescription_id': doc[1].id,
            'status': 'waiting',
            'timestamp': datetime.now().isoformat(),
            'owner_id': current_uid()     # ✅
        })
        flash("Prescription submitted.")
        return redirect(url_for('receipt', prescription_id=doc[1].id))

    medicines = list(with_owner(db.collection('medicines')).stream())
    patients = list(with_owner(db.collection('patients')).stream())
    return render_template('create_prescription.html', medicines=medicines, patients=patients)

# ================= Receipt View =================
@app.route('/receipt/<prescription_id>')
def receipt(prescription_id):
    require_login()
    presc_ref = db.collection('prescriptions').document(prescription_id)
    presc_doc = presc_ref.get()
    if not (presc_doc.exists and presc_doc.to_dict().get('owner_id') == current_uid()):
        flash('❌ Prescription not found.')
        return redirect(url_for('patients'))

    data = presc_doc.to_dict()
    p_ref = db.collection('patients').document(data['patient_id'])
    p_snap = p_ref.get()
    if not (p_snap.exists and p_snap.to_dict().get('owner_id') == current_uid()):
        flash('❌ Patient not found.')
        return redirect(url_for('patients'))
    patient = p_snap.to_dict()
    patient['id'] = p_ref.id  # helpful for hidden fields in the template

    # ✅ Fetch latest confirmed visit for this patient (owned by current user)
    saved_services = []
    visits_q = (p_ref.collection('visits')
                .where('owner_id', '==', current_uid())
                .where('status', '==', 'confirmed')
                .order_by('date', direction=firestore.Query.DESCENDING)
                .limit(1)
                .stream())
    latest_visit = next(visits_q, None)
    if latest_visit:
        vdata = latest_visit.to_dict()
        saved_services = vdata.get('services', []) or []

    return render_template(
        'receipts.html',
        patient=patient,
        items=data['items'],
        total=data['total'],
        services=saved_services  # ← read-only, straight from the visit
    )


@app.route('/receipt/queue/<queue_id>')
def queue_receipt(queue_id):
    require_login()

    queue_ref = db.collection('front_desk_queue').document(queue_id)
    q_snap = queue_ref.get()
    if not q_snap.exists:
        flash('❌ Queue item not found.')
        return redirect(url_for('front_desk'))

    queue_data = q_snap.to_dict()
    if queue_data.get('owner_id') != current_uid():
        flash('❌ Queue item not found.')
        return redirect(url_for('front_desk'))

    # Patient
    p_ref = db.collection('patients').document(queue_data.get('patient_id', ''))
    p_snap = p_ref.get()
    if not (p_snap.exists and p_snap.to_dict().get('owner_id') == current_uid()):
        flash('❌ Patient not found.')
        return redirect(url_for('front_desk'))
    patient = p_snap.to_dict()
    patient['id'] = p_ref.id

    # Build medicine items/totals (unchanged)
    items = []
    total = 0.0
    for i in queue_data.get('items', []):
        unit = (i.get('dosage') or '').strip()
        qty = int(i.get('quantity', 0))
        med_q = with_owner(db.collection('medicines')).where('name', '==', i.get('name', '')).limit(1).stream()
        med = next(med_q, None)
        if med:
            m = med.to_dict()
            price = float(m.get('price', 0.0))
            subtotal = price * qty
            total += subtotal
            items.append({
                'name': m.get('name', i.get('name', '')),
                'unit_price': price,
                'quantity': qty,
                'unit': unit,
                'subtotal': subtotal,
            })
        else:
            items.append({
                'name': i.get('name', ''),
                'unit_price': 0.0,
                'quantity': qty,
                'unit': unit,
                'subtotal': 0.0,
            })

    # ✅ NEW: read services from the linked visit
    saved_services = []
    visit_id = queue_data.get('visit_id')
    if visit_id:
        vref = p_ref.collection('visits').document(visit_id)
        vsnap = vref.get()
        if vsnap.exists and vsnap.to_dict().get('owner_id') == current_uid():
            saved_services = vsnap.to_dict().get('services', []) or []

    return render_template(
        'receipts.html',
        patient=patient,
        items=items,
        total=round(total, 2),
        services=saved_services,                     # ← rename this key
        queue_data={'id': queue_id, 'visit_id': visit_id}
    )
@app.route('/generate_receipt_pdf', methods=['POST'])
def generate_receipt_pdf():
    # ---------- Font setup (CJK) ----------
    CH_REG = None   # name of registered regular CJK font
    CH_BOLD = None  # name of registered bold CJK font (optional)

    # Try project-local Noto Sans CJK first
    try:
        font_dir = os.path.join(app.root_path, 'static', 'fonts')
        reg_path = os.path.join(font_dir, 'NotoSansCJKsc-Regular.otf')
        bold_path = os.path.join(font_dir, 'NotoSansCJKsc-Bold.otf')
        if os.path.exists(reg_path):
            pdfmetrics.registerFont(TTFont('NotoSansCJKsc-Regular', reg_path))
            CH_REG = 'NotoSansCJKsc-Regular'
        if os.path.exists(bold_path):
            pdfmetrics.registerFont(TTFont('NotoSansCJKsc-Bold', bold_path))
            CH_BOLD = 'NotoSansCJKsc-Bold'
    except Exception:
        pass

    # Fallback to built-in CID font if Noto not present
    if not CH_REG:
        pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
        CH_REG = 'STSong-Light'
        # CID fallback has no separate bold; we'll reuse regular for bold lines
        CH_BOLD = CH_REG

    patient_name = request.form.get('patient_name', 'Patient')
    visit_date = datetime.now().strftime("%d-%m-%Y")
    bill_no = f"{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # ---------- Helpers ----------
    def _parse_float(val, default=0.0):
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def _parse_numeric_label(label, default=1):
        """
        Extract a number from strings like '32 grams' or '1.5 bottle'.
        Returns int if whole number, else rounded float. Falls back to default.
        """
        if label is None:
            return default
        s = str(label).strip()
        try:
            return int(s)
        except Exception:
            pass
        m = re.search(r'(\d+(?:\.\d+)?)', s)
        if not m:
            return default
        try:
            num = float(m.group(1))
            return int(num) if num.is_integer() else round(num, 2)
        except Exception:
            return default

    # ---------- Medicines ----------
    medicine_count = int(request.form.get('medicine_count', 0) or 0)
    prescribed_medicines = []  # (name, qty_label, price, subtotal)
    medicine_total = 0.0

    for i in range(1, medicine_count + 1):
        name = request.form.get(f'medicine_name_{i}') or ''
        price = _parse_float(request.form.get(f'medicine_price_{i}', 0), 0.0)
        qty_label = request.form.get(f'medicine_qty_{i}', '1')  # e.g. "32 grams"
        qty_num = _parse_numeric_label(qty_label, default=1)

        # If the checkbox for this medicine was not ticked, skip it
        if not request.form.get(f'use_med_{i}'):
            continue

        subtotal = price * (qty_num if isinstance(qty_num, (int, float)) else 1)
        prescribed_medicines.append((name, qty_label, price, subtotal))
        medicine_total += subtotal

    # ---------- Services ----------
    services = []        # (service_name, amount)
    service_total = 0.0
    for key in request.form.keys():
        if key.startswith('service_'):
            index = key.split('_', 1)[1]
            service_name = request.form.get(key) or ''
            amount = _parse_float(request.form.get(f'amount_{index}', 0), 0.0)
            if request.form.get(f'use_{index}'):
                services.append((service_name, amount))
                service_total += amount

    grand_total = medicine_total + service_total

    # If nothing is selected but a custom description and total are provided,
    # use that single line in the receipt instead.
    custom_desc = (request.form.get('custom_description') or '').strip()
    custom_total_raw = request.form.get('custom_grand_total')
    if not prescribed_medicines and not services and custom_desc and custom_total_raw:
        custom_total = _parse_float(custom_total_raw, 0.0)
        if custom_total >= 0:
            services.append((custom_desc, custom_total))
            service_total = custom_total
            grand_total = custom_total

    # ---------- PDF ----------
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Header — use CJK font for Chinese line; you can also use it for all text if you prefer
    p.setFont(CH_BOLD or CH_REG, 16)
    p.drawCentredString(width/2, height - 40, "春秋堂中医药诊所")

    p.setFont("Helvetica-Bold", 14)  # Latin text can stay in Helvetica
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

    # Table layout
    y -= 70
    row_height = 20
    table_left = 50
    table_right = width - 50
    total_rows = len(prescribed_medicines) + len(services) + 2  # + header + total row
    table_height = total_rows * row_height
    table_top = y
    table_bottom = y - table_height

    p.setFont("Helvetica", 10)
    p.rect(table_left, table_bottom, table_right - table_left, table_height)

    # Table header
    p.setFont("Helvetica-Bold", 11)
    p.line(table_left, table_top - row_height, table_right, table_top - row_height)
    p.drawString(table_left + 10, table_top - 15, "Services Rendered")
    p.drawRightString(table_right - 10, table_top - 15, "Amount (S$)")

    y_cursor = table_top - row_height
    p.setFont("Helvetica", 10)

    # Medicines rows
    for name, qty_label, price, subtotal in prescribed_medicines:
        y_cursor -= row_height
        p.line(table_left, y_cursor, table_right, y_cursor)
        p.drawString(table_left + 10, y_cursor + 5, f"{name} ({qty_label} @ ${price:.2f})")
        p.drawRightString(table_right - 10, y_cursor + 5, f"{subtotal:.2f}")

    # Services rows
    for name, amount in services:
        y_cursor -= row_height
        p.line(table_left, y_cursor, table_right, y_cursor)
        p.drawString(table_left + 10, y_cursor + 5, name)
        p.drawRightString(table_right - 10, y_cursor + 5, f"{amount:.2f}")

    # Total row
    y_cursor -= row_height
    p.line(table_left, y_cursor, table_right, y_cursor)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(table_left + 10, y_cursor + 5, "Total")
    p.drawRightString(table_right - 10, y_cursor + 5, f"{grand_total:.2f}")

    # Footer lines
    p.line(60, 60, 160, 60)
    p.drawString(80, 45, "Date")
    p.line(width - 200, 60, width - 100, 60)
    p.drawString(width - 180, 45, "Physician's Signature")

    p.showPage()
    p.save()
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"Receipt_{bill_no}.pdf",
        mimetype='application/pdf'
    )


# ================= Front Desk View =================

@app.route('/front_desk')
def front_desk():
    require_login()

    # Pull this user's queue items, newest first
    queue = with_owner(db.collection('front_desk_queue')) \
        .order_by('timestamp', direction=firestore.Query.DESCENDING) \
        .stream()

    waiting, completed = [], []

    for entry in queue:
        doc = entry.to_dict()

        # Patient details (guard against cross-tenant or deleted patients)
        p_ref = db.collection('patients').document(doc.get('patient_id', ''))
        p_snap = p_ref.get()
        patient = p_snap.to_dict() if (p_snap.exists and p_snap.to_dict().get('owner_id') == current_uid()) else None
        patient_name = patient.get('name') if patient else 'Unknown (Deleted/Other Tenant)'

        item = {
            'id': entry.id,
            'status': doc.get('status', 'waiting'),
            'patient_name': patient_name,
            # items: list of {'name', 'quantity', 'dosage'}; keep as-is so template can show unit
            'items': doc.get('items', [])
        }

        if item['status'] == 'completed':
            completed.append(item)
        else:
            waiting.append(item)

    return render_template('front_desk.html', waiting=waiting, completed=completed)


@app.route('/front_desk/update/<queue_id>/<status>')
def update_queue_status(queue_id, status):
    require_login()
    queue_ref = db.collection('front_desk_queue').document(queue_id)
    queue_doc = queue_ref.get().to_dict()

    if not queue_doc or queue_doc.get('owner_id') != current_uid():
        flash('❌ Queue item not found.')
        return redirect(url_for('front_desk'))

    items = queue_doc.get('items', [])
    current_status = queue_doc.get('status')

    if status == 'completed':
        # Decrement stock when marking as completed (only within this owner’s medicines)
        for med in items:
            query = with_owner(db.collection('medicines')).where('name', '==', med['name']).limit(1).stream()
            found = next(query, None)
            if found:
                ref = db.collection('medicines').document(found.id)
                med_doc = found.to_dict()
                new_stock = max(med_doc.get('stock', 0) - int(med['quantity']), 0)
                ref.update({'stock': new_stock})

        queue_ref.update({'status': 'completed'})
        return redirect(url_for('queue_receipt', queue_id=queue_id))

    elif status == 'void':
        # Revert stock if voiding a completed order
        if current_status == 'completed':
            for med in items:
                query = with_owner(db.collection('medicines')).where('name', '==', med['name']).limit(1).stream()
                found = next(query, None)
                if found:
                    ref = db.collection('medicines').document(found.id)
                    med_doc = found.to_dict()
                    new_stock = med_doc.get('stock', 0) + int(med['quantity'])
                    ref.update({'stock': new_stock})

        queue_ref.update({'status': 'waiting'})
        return redirect(url_for('front_desk'))

    # Just update status otherwise
    queue_ref.update({'status': status})
    return redirect(url_for('front_desk'))


# ================= dashboard =================
@app.route('/admin/dashboard')
def admin_dashboard():
    require_login()

    # --- NEW: read date range from query params ---
    today = datetime.now().date().isoformat()
    start_date = request.args.get('start_date') or today
    end_date = request.args.get('end_date') or today

    # Ensure start_date <= end_date (since they're ISO strings this works)
    if start_date > end_date:
        start_date, end_date = end_date, start_date

    # Patients count
    total_patients = len(list(with_owner(db.collection('patients')).stream()))

    # Visits in selected date range (collection group filtered by owner)
    visits_filtered = []
    visits_ref = with_owner(db.collection_group('visits')).stream()
    for v in visits_ref:
        data = v.to_dict()
        vdate = data.get('date')
        if vdate and start_date <= vdate <= end_date:
            patient_id = v.reference.parent.parent.id
            p_snap = db.collection('patients').document(patient_id).get()
            patient = (
                p_snap.to_dict()
                if (p_snap.exists and p_snap.to_dict().get('owner_id') == current_uid())
                else None
            )
            visits_filtered.append({
                'patient': patient['name'] if patient else 'Unknown',
                'condition': data.get('condition'),
                'date': data.get('date')
            })

    # Prescriptions count
    total_prescriptions = len(list(with_owner(db.collection('prescriptions')).stream()))

    # Low stock medicines
    low_stock = []
    for m in with_owner(db.collection('medicines')).stream():
        data = m.to_dict()
        if data.get('stock', 0) <= 10:
            low_stock.append(data)

    # Recent completed queue items
    completed_queue = (
        with_owner(db.collection('front_desk_queue'))
        .where('status', '==', 'completed')
        .order_by('timestamp', direction=firestore.Query.DESCENDING)
        .limit(5)
        .stream()
    )

    recent_completed = []
    for item in completed_queue:
        doc = item.to_dict()
        pid = doc.get('patient_id')
        p_snap = db.collection('patients').document(pid).get()
        patient = (
            p_snap.to_dict()
            if (p_snap.exists and p_snap.to_dict().get('owner_id') == current_uid())
            else None
        )
        recent_completed.append({
            'patient_name': patient['name'] if patient else 'Unknown',
            'status': doc['status'],
            'items': doc.get('items', []),
            'timestamp': doc.get('timestamp', '')
        })

    return render_template(
        "admin_dashboard.html",
        total_patients=total_patients,
        daily_visits=len(visits_filtered),     # now "visits in range"
        total_prescriptions=total_prescriptions,
        low_stock=low_stock,
        today_visits=visits_filtered,          # list for table
        recent_completed=recent_completed,
        filter_start=start_date,               # NEW: for pre-filling inputs
        filter_end=end_date                    # NEW: for pre-filling inputs
    )


@app.route('/admin/export/visits.csv')
def export_visits_csv():
    require_login()
    all_visits = []
    patients = with_owner(db.collection('patients')).stream()

    for p in patients:
        pdata = p.to_dict()
        visits = db.collection('patients').document(p.id).collection('visits')\
            .where('owner_id', '==', current_uid()).stream()
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
    require_login()
    queue_data = []
    queue = with_owner(db.collection('front_desk_queue')).stream()
    for q in queue:
        qdata = q.to_dict()
        p_snap = db.collection('patients').document(qdata.get('patient_id')).get()
        patient = p_snap.to_dict() if (p_snap.exists and p_snap.to_dict().get('owner_id') == current_uid()) else None
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
    require_login()
    date_str = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')

    # Load bookings for selected date
    appointment_docs = with_owner(db.collection('appointments'))\
        .where('date', '==', date_str).stream()
    patients = []
    appointment_data = {}
    for doc in appointment_docs:
        data = doc.to_dict()
        name = data['patient_name']
        contact = data.get('contact', '')
        patients.append({'name': name, 'contact': contact})
        appointment_data[name] = data.get('slots', {})

    # Count bookings per day for calendar coloring
    all_docs = with_owner(db.collection('appointments')).stream()
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
    require_login()
    form = request.form.to_dict()
    date_str = form.get('date') or datetime.now().strftime('%Y-%m-%d')

    appointment_batches = []
    row_num = 1
    while f"patient_name_{row_num}" in form:
        patient_name = form.get(f"patient_name_{row_num}")
        contact = form.get(f"contact_{row_num}", "")
        slots = {}
        for hour in range(10, 21):
            slot_value = form.get(f"slot_{row_num}_{hour}", "")
            slots[str(hour)] = slot_value

        appointment_batches.append({
            'patient_name': patient_name,
            'contact': contact,
            'slots': slots,
            'date': date_str,
            'timestamp': datetime.now().isoformat(),
            'owner_id': current_uid()   # ✅
        })
        row_num += 1

    # Replace existing for this date & owner
    for doc in with_owner(db.collection('appointments')).where('date', '==', date_str).stream():
        doc.reference.delete()

    for batch in appointment_batches:
        db.collection('appointments').add(batch)

    flash(f"Appointments saved for {date_str}")
    return redirect(url_for('appointments_combined', date=date_str))

@app.route('/appointments/json')
def appointments_json():
    require_login()
    date_str = request.args.get('date')
    if not date_str:
        return {'patients': []}

    appointment_docs = with_owner(db.collection('appointments')).where('date', '==', date_str).stream()
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
    require_login()
    patient_name = request.form.get('patient_name')
    date = request.form.get('date')

    docs = with_owner(db.collection('appointments')) \
        .where('patient_name', '==', patient_name) \
        .where('date', '==', date).stream()

    for doc in docs:
        doc.reference.delete()

    return '', 204

@app.route('/appointments/event_counts')
def appointment_event_counts():
    require_login()
    booking_counts = defaultdict(int)

    all_docs = with_owner(db.collection('appointments')).stream()
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
        username = request.form['username'].strip()
        email = f"{username}@gmail.com"
        password = request.form['password']

        try:
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
                uid = res['localId']
                session['user'] = uid

                user_doc = db.collection("users").document(uid).get()
                role = user_doc.to_dict().get("role", "staff") if user_doc.exists else "staff"
                session['role'] = role

                flash("✅ Login successful.")

                if role == "super_admin":
                    return redirect(url_for("admin_users"))

                return redirect(url_for("patients"))

            else:
                flash("❌ Invalid credentials.")

        except Exception as e:
            flash(f"❌ Error: {str(e)}")

    return render_template('login.html')


def require_super_admin():
    if session.get("role") != "super_admin":
        flash("❌ Access denied.")
        return redirect(url_for("patients"))
    return None

@app.route("/admin/users")
def admin_users():
    require_login()
    deny = require_super_admin()
    if deny: return deny

    users = []
    for doc in db.collection("users").stream():
        d = doc.to_dict()
        d["uid"] = doc.id
        users.append(d)

    return render_template("admin_users.html", users=users)

@app.route("/admin/users/create", methods=["GET", "POST"])
def admin_users_create():
    require_login()
    deny = require_super_admin()
    if deny: return deny

    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"]
        role = request.form["role"]

        new_user = auth.create_user(email=email, password=password)

        db.collection("users").document(new_user.uid).set({
            "email": email,                 # ✅ REQUIRED
            "role": role,
            "created_by": session.get("user"),
            "created_at": datetime.now().isoformat(),
            "active": True
        })


        flash("✅ User created.")
        return redirect(url_for("admin_users"))

    return render_template("create_user.html")

def require_admin():
    if session.get("role") not in ("admin", "super_admin"):
        flash("❌ Access denied.")
        return redirect(url_for("home"))
@app.route("/admin/users/create", methods=["GET", "POST"])
def create_user():
    require_login()
    if require_super_admin():
        return require_super_admin()

    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        role = request.form["role"]

        new_user = auth.create_user(
            email=email,
            password=password
        )

        db.collection("users").document(new_user.uid).set({
            "role": role,
            "created_by": session["user"],
            "created_at": datetime.now().isoformat(),
            "active": True
        })

        flash("✅ User created successfully.")
        return redirect(url_for("list_users"))

    return render_template("create_user.html")
@app.route("/admin/users")
def list_users():
    require_login()
    if require_super_admin():
        return require_super_admin()

    users = []
    for doc in db.collection("users").stream():
        d = doc.to_dict()
        uid = doc.id
        d["uid"] = uid

        # 🔹 Backfill email if missing
        if not d.get("email"):
            try:
                auth_user = auth.get_user(uid)
                d["email"] = auth_user.email

                # Optional: save back to Firestore so next load is fast
                db.collection("users").document(uid).update({
                    "email": auth_user.email
                })
            except Exception:
                d["email"] = "Unknown"

        users.append(d)


    return render_template("users.html", users=users)

@app.cli.command("create-super-admin")
@click.option("--email", prompt=True, help="Email for the super admin")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True,
              help="Password for the super admin")

# create new super admin user
# CLI cmd: flask create-super-admin --email superadmin@gmail.com --password Admin123
def create_super_admin_cli(email, password):
    """Create a Super Admin user (CLI)"""

    try:
        # Check if user already exists
        existing = auth.get_user_by_email(email)
        print(f"⚠️ User already exists: {existing.uid}")
        return

    except auth.UserNotFoundError:
        user = auth.create_user(
            email=email,
            password=password
        )

        db.collection("users").document(user.uid).set({
            "role": "super_admin",
            "created_by": "system",
            "created_at": datetime.now().isoformat(),
            "active": True
        })

        print("✅ Super Admin created:", user.uid)

@app.route("/admin/users/<uid>/edit", methods=["GET", "POST"])
def admin_user_edit(uid):
    # --- Auth guards ---
    require_login()
    deny = require_super_admin()
    if deny:
        return deny

    # --- Load user record from Firestore ---
    ref = db.collection("users").document(uid)
    snap = ref.get()
    if not snap.exists:
        flash("❌ User record not found.")
        return redirect(url_for("admin_users"))

    user_data = snap.to_dict() or {}
    # ✅ Backfill email if missing (so edit page can show it)
    if not user_data.get("email"):
        try:
            auth_user = auth.get_user(uid)
            if auth_user.email:
                user_data["email"] = auth_user.email
                # optional: save into Firestore so next time it’s there
                ref.update({"email": auth_user.email})
        except Exception:
            user_data["email"] = None


    if request.method == "POST":
        # --- Read form values ---
        new_role = request.form.get("role", user_data.get("role", "staff")).strip()
        active = True if request.form.get("active") == "on" else False
        new_email = (request.form.get("new_email") or "").strip()
        new_password = (request.form.get("new_password") or "").strip()

        # --- Safety: prevent disabling yourself ---
        if uid == session.get("user") and not active:
            flash("❌ You cannot disable your own account.")
            return redirect(url_for("admin_user_edit", uid=uid))

        # --- Safety: prevent removing the LAST super_admin ---
        # If you're changing role away from super_admin OR disabling a super_admin,
        # ensure there will still be at least one active super_admin left.
        is_target_super_admin = (user_data.get("role") == "super_admin")
        removing_super = is_target_super_admin and (new_role != "super_admin")
        disabling_super = is_target_super_admin and (not active)

        if removing_super or disabling_super:
            # Count active super_admins
            super_admin_count = 0
            for doc in db.collection("users").where("role", "==", "super_admin").stream():
                d = doc.to_dict() or {}
                if d.get("active", True):
                    super_admin_count += 1

            # If target is currently an active super admin, then this action would reduce count by 1
            # (unless it was already inactive)
            target_is_active = user_data.get("active", True)
            would_reduce = target_is_active and (removing_super or disabling_super)

            if would_reduce and super_admin_count <= 1:
                flash("❌ You cannot remove/disable the last active super admin.")
                return redirect(url_for("admin_user_edit", uid=uid))

        # --- Apply Firebase Auth updates (email/password) if provided ---
        try:
            auth_updates = {}
            if new_email:
                auth_updates["email"] = new_email
            if new_password:
                auth_updates["password"] = new_password

            if auth_updates:
                auth.update_user(uid, **auth_updates)

            # --- Update Firestore user profile ---
            updates = {
                "role": new_role,
                "active": active,
                "updated_at": datetime.now().isoformat(),
                "updated_by": session.get("user"),
            }
            if new_email:
                updates["email"] = new_email  # keep Firestore in sync for display/search

            ref.update(updates)

            flash("✅ User updated.")
            return redirect(url_for("admin_users"))

        except Exception as e:
            flash(f"❌ Update failed: {str(e)}")
            # fall through to re-render the page with current data

        # reload latest data if something changed partially
        snap = ref.get()
        user_data = snap.to_dict() or {}

    # --- GET (or failed POST): render edit page ---
    return render_template("edit_user.html", u={"uid": uid, **user_data})


@app.route('/logout')
def logout():
    session.clear()
    flash("✅ You have been logged out.")
    return redirect(url_for('login'))


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

# import medicine

def _norm(s):
    return (str(s).strip() if s is not None else "")

def _to_int(val, default=0):
    try:
        return int(float(str(val).strip()))
    except Exception:
        return default

def _to_float(val, default=0.0):
    try:
        return float(str(val).strip())
    except Exception:
        return default

def _get_ci(row: dict, key: str):
    key = key.lower()
    for k in row.keys():
        if k and k.strip().lower() == key:
            return row.get(k)
    return None

def _gen_sku():
    return "TCM-" + uuid.uuid4().hex[:8].upper()

def _flush_medicine_batch(pending_ops):
    batch = db.batch()
    added = 0
    updated = 0

    for op, doc_id, data in pending_ops:
        if op == "update" and doc_id:
            ref = db.collection("medicines").document(doc_id)
            batch.set(ref, data, merge=True)
            updated += 1
        else:
            ref = db.collection("medicines").document()
            batch.set(ref, data, merge=True)
            added += 1

    batch.commit()
    return added, updated


@app.route("/inventory/import_csv", methods=["POST"])
def import_inventory_csv():
    require_login()

    f = request.files.get("csv_file")
    if not f or not f.filename:
        flash("❌ Please choose a CSV file.")
        return redirect(url_for("inventory"))

    if not f.filename.lower().endswith(".csv"):
        flash("❌ File must be a .csv")
        return redirect(url_for("inventory"))

    try:
        stream = (line.decode("utf-8-sig") for line in f.stream)
        reader = csv.DictReader(stream)
        rows = list(reader)
    except Exception as e:
        flash(f"❌ CSV read error: {e}")
        return redirect(url_for("inventory"))

    if not rows:
        flash("❌ CSV is empty.")
        return redirect(url_for("inventory"))

    owner = current_uid()
    added = updated = skipped = 0
    pending = []
    BATCH_LIMIT = 450

    for r in rows:
        sku_id = _norm(_get_ci(r, "sku_id"))
        name = _norm(_get_ci(r, "name"))
        company = _norm(_get_ci(r, "company"))
        med_type = _norm(_get_ci(r, "type"))
        expiry_date = normalize_expiry_to_iso(_norm(_get_ci(r, "expiry_date")))
        price = _to_float(_get_ci(r, "price"), 0.0)
        quantity = _to_int(_get_ci(r, "quantity"), 0)

        if not name:
            skipped += 1
            continue

        match = None

        # 1️⃣ Try sku_id match (best)
        if sku_id:
            q = with_owner(db.collection("medicines")).where("sku_id", "==", sku_id)
            match = next(q.limit(1).stream(), None)

        # 2️⃣ Fallback match (for CSVs without sku_id)
        if not match:
            q = with_owner(db.collection("medicines")) \
                .where("name", "==", name) \
                .where("company", "==", company) \
                .where("type", "==", med_type) \
                .where("expiry_date", "==", expiry_date)
            match = next(q.limit(1).stream(), None)

        # 3️⃣ Auto-generate sku_id if needed
        if not sku_id:
            sku_id = match.to_dict().get("sku_id") if match else _gen_sku()

        data = {
            "sku_id": sku_id,
            "name": name,
            "company": company,
            "type": med_type,
            "price": price,
            "stock": quantity,
            "expiry_date": expiry_date,
            "owner_id": owner
        }

        if match:
            pending.append(("update", match.id, data))
        else:
            pending.append(("add", None, data))

        if len(pending) >= BATCH_LIMIT:
            a, u = _flush_medicine_batch(pending)
            added += a
            updated += u
            pending = []

    if pending:
        a, u = _flush_medicine_batch(pending)
        added += a
        updated += u

    flash(f"✅ Import done. Added: {added}, Updated: {updated}, Skipped: {skipped}")
    return redirect(url_for("inventory"))

@app.before_request
def check_auth():
    # Allow access to login, static files, language toggle without login
    open_endpoints = {'login', 'logout', 'switch_language', 'static'}
    if (request.endpoint not in open_endpoints) and ('user' not in session):
        return redirect(url_for('login'))



# ================= Run =================
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)

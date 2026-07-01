#!/usr/bin/env python3
import os, sys, json, sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, g, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'sklad.db')
SCHEMA_PATH = os.path.join(BASE_DIR, 'schema.sql')

app = Flask(__name__, static_folder='static', static_url_path='')

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA journal_mode=WAL')
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    if os.path.exists(SCHEMA_PATH):
        with sqlite3.connect(DB_PATH) as conn:
            with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
                conn.executescript(f.read())
            conn.commit()
        print('[OK] Database initialized')

def query(sql, params=(), one=False):
    db = get_db()
    cur = db.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    return rows[0] if one and rows else (rows if not one else None)

def execute(sql, params=()):
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    return cur.lastrowid

def crud_list(table, order_by='id DESC', where='1=1', params=()):
    return query(f'SELECT * FROM {table} WHERE {where} ORDER BY {order_by}', params)

def crud_get(table, id_val, id_col='id'):
    return query(f'SELECT * FROM {table} WHERE {id_col}=?', (id_val,), one=True)

def crud_create(table, data, allowed_cols=None):
    if allowed_cols:
        data = {k: v for k, v in data.items() if k in allowed_cols}
    cols = ', '.join(data.keys())
    ph = ', '.join(['?'] * len(data))
    rid = execute(f'INSERT INTO {table} ({cols}) VALUES ({ph})', list(data.values()))
    return crud_get(table, rid)

def crud_update(table, id_val, data, allowed_cols=None, id_col='id'):
    if allowed_cols:
        data = {k: v for k, v in data.items() if k in allowed_cols}
    if not data: return None
    sets = ', '.join([f'{k}=?' for k in data.keys()])
    execute(f'UPDATE {table} SET {sets} WHERE {id_col}=?', list(data.values()) + [id_val])
    return crud_get(table, id_val, id_col)

def crud_delete(table, id_val, id_col='id'):
    execute(f'DELETE FROM {table} WHERE {id_col}=?', (id_val,))

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/units')
def api_units():
    return jsonify(crud_list('units', 'id ASC'))

@app.route('/api/categories', methods=['GET', 'POST'])
def api_categories():
    if request.method == 'POST':
        r = crud_create('categories', request.json,
            ['name', 'description', 'sort_order', 'is_active'])
        return jsonify(r), 201
    return jsonify(crud_list('categories', 'sort_order ASC, name ASC'))

@app.route('/api/categories/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def api_category(id):
    if request.method == 'GET':
        r = crud_get('categories', id)
        return jsonify(r if r else ('Not found', 404))
    elif request.method == 'PUT':
        r = crud_update('categories', id, request.json,
            ['name', 'description', 'sort_order', 'is_active'])
        return jsonify(r if r else ('Not found', 404))
    elif request.method == 'DELETE':
        crud_delete('categories', id)
        return jsonify({'ok': True})

@app.route('/api/suppliers', methods=['GET', 'POST'])
def api_suppliers():
    if request.method == 'POST':
        r = crud_create('suppliers', request.json,
            ['name', 'address', 'phone', 'contact_person', 'website', 'notes'])
        return jsonify(r), 201
    return jsonify(crud_list('suppliers', 'name ASC'))

@app.route('/api/suppliers/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def api_supplier(id):
    if request.method == 'GET':
        return jsonify(crud_get('suppliers', id) or ('Not found', 404))
    elif request.method == 'PUT':
        r = crud_update('suppliers', id, request.json,
            ['name', 'address', 'phone', 'contact_person', 'website', 'notes'])
        return jsonify(r if r else ('Not found', 404))
    elif request.method == 'DELETE':
        crud_delete('suppliers', id)
        return jsonify({'ok': True})

@app.route('/api/catalog', methods=['GET'])
def api_catalog_list():
    search = request.args.get('search', '').lower()
    cat = request.args.get('category', '')
    where = '1=1'
    params = []
    if cat:
        where += ' AND c.name = ?'
        params.append(cat)
    sql = f'''
        SELECT uc.*, c.name AS category_name, u.short_name AS unit_name,
               (SELECT COUNT(*) FROM catalog_aliases ca WHERE ca.catalog_id=uc.id) AS alias_count
        FROM unified_catalog uc
        JOIN categories c ON uc.category_id=c.id
        JOIN units u ON uc.unit_id=u.id
        WHERE {where}
        ORDER BY c.name ASC, uc.unified_name ASC
    '''
    rows = query(sql, params)
    if search:
        rows = [r for r in rows if search in r['unified_name'].lower() or (r.get('description') and search in r['description'].lower())]
    return jsonify(rows)

@app.route('/api/catalog', methods=['POST'])
def api_catalog_create():
    data = request.json
    allowed = ['category_id', 'unified_name', 'unit_id', 'description',
               'photo_path', 'supplier_url', 'notes', 'min_stock']
    r = crud_create('unified_catalog', data, allowed)
    if 'aliases' in data and data['aliases']:
        for alias in data['aliases']:
            execute(
                'INSERT OR IGNORE INTO catalog_aliases (catalog_id, supplier_id, alias_name) VALUES (?,?,?)',
                (r['id'], alias.get('supplier_id'), alias.get('alias_name', '')))
    return jsonify(crud_get('unified_catalog', r['id'])), 201

@app.route('/api/catalog/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def api_catalog_item(id):
    if request.method == 'GET':
        item = query('''
            SELECT uc.*, c.name AS category_name, u.short_name AS unit_name
            FROM unified_catalog uc
            JOIN categories c ON uc.category_id=c.id
            JOIN units u ON uc.unit_id=u.id
            WHERE uc.id=?
        ''', (id,), one=True)
        if item:
            item['aliases'] = query(
                '''SELECT ca.*, s.name AS supplier_name FROM catalog_aliases ca
                   LEFT JOIN suppliers s ON ca.supplier_id=s.id
                   WHERE ca.catalog_id=?''', (id,))
        return jsonify(item if item else ('Not found', 404))
    elif request.method == 'PUT':
        data = request.json
        allowed = ['category_id', 'unified_name', 'unit_id', 'description',
                   'photo_path', 'supplier_url', 'notes', 'min_stock']
        data['updated_at'] = datetime.now().isoformat()
        r = crud_update('unified_catalog', id, data, allowed)
        return jsonify(r if r else ('Not found', 404))
    elif request.method == 'DELETE':
        execute('DELETE FROM catalog_aliases WHERE catalog_id=?', (id,))
        crud_delete('unified_catalog', id)
        return jsonify({'ok': True})

# Aliases
@app.route('/api/catalog/<int:catalog_id>/aliases', methods=['GET', 'POST'])
def api_aliases(catalog_id):
    if request.method == 'POST':
        data = request.json
        execute(
            'INSERT OR IGNORE INTO catalog_aliases (catalog_id, supplier_id, alias_name) VALUES (?,?,?)',
            (catalog_id, data['supplier_id'], data['alias_name']))
        return jsonify({'ok': True}), 201
    return jsonify(query(
        '''SELECT ca.*, s.name AS supplier_name FROM catalog_aliases ca
           LEFT JOIN suppliers s ON ca.supplier_id=s.id
           WHERE ca.catalog_id=?''', (catalog_id,)))

@app.route('/api/aliases/<int:alias_id>', methods=['DELETE'])
def api_alias_delete(alias_id):
    execute('DELETE FROM catalog_aliases WHERE id=?', (alias_id,))
    return jsonify({'ok': True})

# Objects
@app.route('/api/objects', methods=['GET', 'POST'])
def api_objects():
    if request.method == 'POST':
        r = crud_create('objects', request.json,
            ['name', 'address', 'height_floors', 'height_meters', 'notes', 'is_active'])
        return jsonify(r), 201
    rows = query('''
        SELECT o.*,
               (SELECT COUNT(*) FROM equipment e WHERE e.current_object_id=o.id) AS equipment_count,
               (SELECT GROUP_CONCAT(DISTINCT c.name) FROM equipment e
                JOIN contractors c ON e.current_contractor_id=c.id
                WHERE e.current_object_id=o.id) AS contractor_names
        FROM objects o ORDER BY o.is_active DESC, o.name ASC
    ''')
    return jsonify(rows)

@app.route('/api/objects/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def api_object(id):
    if request.method == 'GET':
        r = crud_get('objects', id)
        if r:
            r['equipment'] = query(
                'SELECT id, serial_number, inventory_number, status FROM equipment WHERE current_object_id=?',
                (id,))
        return jsonify(r if r else ('Not found', 404))
    elif request.method == 'PUT':
        r = crud_update('objects', id, request.json,
            ['name', 'address', 'height_floors', 'height_meters', 'notes', 'is_active'])
        return jsonify(r if r else ('Not found', 404))
    elif request.method == 'DELETE':
        crud_delete('objects', id)
        return jsonify({'ok': True})

# Contractors
@app.route('/api/contractors', methods=['GET', 'POST'])
def api_contractors():
    if request.method == 'POST':
        r = crud_create('contractors', request.json,
            ['name', 'phone', 'company', 'notes'])
        return jsonify(r), 201
    rows = query('''
        SELECT co.*,
               (SELECT COUNT(*) FROM equipment e WHERE e.current_contractor_id=co.id) AS equipment_count,
               COALESCE((SELECT SUM(cf.amount) FROM contractor_fines cf
                         WHERE cf.contractor_id=co.id AND cf.is_paid=0), 0) AS unpaid_fines
        FROM contractors co ORDER BY co.name ASC
    ''')
    return jsonify(rows)

@app.route('/api/contractors/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def api_contractor(id):
    if request.method == 'GET':
        r = crud_get('contractors', id)
        if r:
            r['equipment'] = query(
                'SELECT id, serial_number, inventory_number, status FROM equipment WHERE current_contractor_id=?',
                (id,))
            r['fines'] = query('''
                SELECT cf.*, e.serial_number AS equipment_sn
                FROM contractor_fines cf
                LEFT JOIN equipment e ON cf.equipment_id=e.id
                WHERE cf.contractor_id=? ORDER BY cf.fine_date DESC
            ''', (id,))
        return jsonify(r if r else ('Not found', 404))
    elif request.method == 'PUT':
        r = crud_update('contractors', id, request.json,
            ['name', 'phone', 'company', 'notes'])
        return jsonify(r if r else ('Not found', 404))
    elif request.method == 'DELETE':
        crud_delete('contractors', id)
        return jsonify({'ok': True})

# Equipment
@app.route('/api/equipment', methods=['GET'])
def api_equipment_list():
    status = request.args.get('status', '')
    where = '1=1'
    params = []
    if status:
        where += ' AND e.status=?'
        params.append(status)
    sql = f'''
        SELECT e.*, o.name AS object_name, c.name AS contractor_name
        FROM equipment e
        LEFT JOIN objects o ON e.current_object_id=o.id
        LEFT JOIN contractors c ON e.current_contractor_id=c.id
        WHERE {where}
        ORDER BY e.status, e.serial_number ASC
    '''
    return jsonify(query(sql, params))

@app.route('/api/equipment', methods=['POST'])
def api_equipment_create():
    data = request.json
    allowed = ['equipment_type', 'serial_number', 'inventory_number',
               'status', 'current_object_id', 'current_contractor_id', 'notes']
    r = crud_create('equipment', data, allowed)
    execute('''INSERT INTO equipment_history
               (equipment_id, event_type, event_date, description)
               VALUES (?, 'other', date('now'), 'Added to system')''', (r['id'],))
    return jsonify(r), 201

@app.route('/api/equipment/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def api_equipment(id):
    if request.method == 'GET':
        r = query('''
            SELECT e.*, o.name AS object_name, c.name AS contractor_name
            FROM equipment e
            LEFT JOIN objects o ON e.current_object_id=o.id
            LEFT JOIN contractors c ON e.current_contractor_id=c.id
            WHERE e.id=?
        ''', (id,), one=True)
        if r:
            r['history'] = query('''
                SELECT eh.*, o.name AS object_name, c.name AS contractor_name
                FROM equipment_history eh
                LEFT JOIN objects o ON eh.object_id=o.id
                LEFT JOIN contractors c ON eh.contractor_id=c.id
                WHERE eh.equipment_id=? ORDER BY eh.event_date DESC, eh.id DESC
            ''', (id,))
            r['kits'] = query('''
                SELECT ek.*, o.name AS object_name
                FROM equipment_kits ek
                LEFT JOIN objects o ON ek.object_id=o.id
                WHERE ek.equipment_id=? ORDER BY ek.assembled_date DESC
            ''', (id,))
            r['expenses'] = query('''
                SELECT ex.*, uc.unified_name, u.short_name AS unit_name
                FROM expenses ex
                LEFT JOIN unified_catalog uc ON ex.catalog_id=uc.id
                LEFT JOIN units u ON ex.unit_id=u.id
                WHERE ex.equipment_id=? ORDER BY ex.expense_date DESC
            ''', (id,))
        return jsonify(r if r else ('Not found', 404))
    elif request.method == 'PUT':
        data = request.json
        old = crud_get('equipment', id)
        allowed = ['equipment_type', 'serial_number', 'inventory_number',
                   'status', 'current_object_id', 'current_contractor_id', 'notes']
        r = crud_update('equipment', id, data, allowed)
        if old and r:
            changes = []
            if old.get('status') != r.get('status'):
                changes.append(f'Status: {old.get("status")} -> {r.get("status")}')
            if old.get('current_object_id') != r.get('current_object_id'):
                changes.append('Object changed')
            if old.get('current_contractor_id') != r.get('current_contractor_id'):
                changes.append('Contractor changed')
            if changes:
                execute('''INSERT INTO equipment_history
                           (equipment_id, event_type, event_date, description)
                           VALUES (?, 'move', date('now'), ?)''',
                        (id, '; '.join(changes)))
        return jsonify(r if r else ('Not found', 404))
    elif request.method == 'DELETE':
        crud_delete('equipment', id)
        return jsonify({'ok': True})

# Equipment History
@app.route('/api/equipment/<int:eq_id>/history', methods=['GET', 'POST'])
def api_equipment_history(eq_id):
    if request.method == 'POST':
        data = request.json
        execute('''INSERT INTO equipment_history
                   (equipment_id, event_type, event_date, object_id, contractor_id, description)
                   VALUES (?,?,?,?,?,?)''',
                (eq_id, data['event_type'],
                 data.get('event_date', datetime.now().strftime('%Y-%m-%d')),
                 data.get('object_id'), data.get('contractor_id'),
                 data.get('description', '')))
        return jsonify({'ok': True}), 201
    return jsonify(query('''
        SELECT eh.*, o.name AS object_name, c.name AS contractor_name
        FROM equipment_history eh
        LEFT JOIN objects o ON eh.object_id=o.id
        LEFT JOIN contractors c ON eh.contractor_id=c.id
        WHERE eh.equipment_id=? ORDER BY eh.event_date DESC, eh.id DESC
    ''', (eq_id,)))

# Receipts
@app.route('/api/receipts', methods=['GET'])
def api_receipts_list():
    rows = query('''
        SELECT r.*, s.name AS supplier_name,
               (SELECT COUNT(*) FROM receipt_items ri WHERE ri.receipt_id=r.id) AS item_count
        FROM receipts r
        LEFT JOIN suppliers s ON r.supplier_id=s.id
        ORDER BY r.receipt_date DESC, r.id DESC
    ''')
    return jsonify(rows)

@app.route('/api/receipts', methods=['POST'])
def api_receipts_create():
    data = request.json
    items = data.pop('items', [])
    allowed = ['supplier_id', 'receipt_date', 'invoice_number', 'status', 'comment']
    receipt = crud_create('receipts', data, allowed)
    total = 0
    for item in items:
        item['receipt_id'] = receipt['id']
        item['total_price'] = round(item.get('quantity', 0) * item.get('unit_price', 0), 2)
        total += item['total_price']
        execute('''INSERT INTO receipt_items
                   (receipt_id, catalog_id, item_name, category_id, unit_id,
                    quantity, unit_price, total_price, comment)
                   VALUES (?,?,?,?,?,?,?,?,?)''',
                (receipt['id'], item.get('catalog_id'), item.get('item_name', ''),
                 item.get('category_id'), item.get('unit_id', 1),
                 item.get('quantity', 0), item.get('unit_price', 0),
                 item['total_price'], item.get('comment', '')))
    execute('UPDATE receipts SET total_amount=? WHERE id=?', (total, receipt['id']))
    return jsonify(crud_get('receipts', receipt['id'])), 201

@app.route('/api/receipts/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def api_receipt(id):
    if request.method == 'GET':
        r = query('''
            SELECT r.*, s.name AS supplier_name
            FROM receipts r LEFT JOIN suppliers s ON r.supplier_id=s.id
            WHERE r.id=?
        ''', (id,), one=True)
        if r:
            r['items'] = query('''
                SELECT ri.*, uc.unified_name, c.name AS category_name, u.short_name AS unit_name
                FROM receipt_items ri
                LEFT JOIN unified_catalog uc ON ri.catalog_id=uc.id
                LEFT JOIN categories c ON ri.category_id=c.id
                LEFT JOIN units u ON ri.unit_id=u.id
                WHERE ri.receipt_id=?
            ''', (id,))
        return jsonify(r if r else ('Not found', 404))
    elif request.method == 'PUT':
        data = request.json
        items = data.pop('items', None)
        allowed = ['supplier_id', 'receipt_date', 'invoice_number', 'status', 'comment']
        r = crud_update('receipts', id, data, allowed)
        if items is not None:
            execute('DELETE FROM receipt_items WHERE receipt_id=?', (id,))
            total = 0
            for item in items:
                item['total_price'] = round(item.get('quantity', 0) * item.get('unit_price', 0), 2)
                total += item['total_price']
                execute('''INSERT INTO receipt_items
                           (receipt_id, catalog_id, item_name, category_id, unit_id,
                            quantity, unit_price, total_price, comment)
                           VALUES (?,?,?,?,?,?,?,?,?)''',
                        (id, item.get('catalog_id'), item.get('item_name', ''),
                         item.get('category_id'), item.get('unit_id', 1),
                         item.get('quantity', 0), item.get('unit_price', 0),
                         item['total_price'], item.get('comment', '')))
            execute('UPDATE receipts SET total_amount=? WHERE id=?', (total, id))
        return jsonify(r if r else ('Not found', 404))
    elif request.method == 'DELETE':
        crud_delete('receipts', id)
        return jsonify({'ok': True})

# Expenses
@app.route('/api/expenses', methods=['GET'])
def api_expenses_list():
    where = '1=1'
    params = []
    etype = request.args.get('type', '')
    eq_id = request.args.get('equipment_id', '')
    if etype:
        where += ' AND ex.expense_type=?'
        params.append(etype)
    if eq_id:
        where += ' AND ex.equipment_id=?'
        params.append(int(eq_id))
    sql = f'''
        SELECT ex.*, uc.unified_name, u.short_name AS unit_name,
               e.serial_number AS equipment_sn, c.name AS contractor_name, o.name AS object_name
        FROM expenses ex
        LEFT JOIN unified_catalog uc ON ex.catalog_id=uc.id
        LEFT JOIN units u ON ex.unit_id=u.id
        LEFT JOIN equipment e ON ex.equipment_id=e.id
        LEFT JOIN contractors c ON ex.contractor_id=c.id
        LEFT JOIN objects o ON ex.object_id=o.id
        WHERE {where}
        ORDER BY ex.expense_date DESC, ex.id DESC
    '''
    return jsonify(query(sql, params))

@app.route('/api/expenses', methods=['POST'])
def api_expenses_create():
    data = request.json
    data['total_price'] = round(data.get('quantity', 0) * data.get('unit_price', 0), 2)
    allowed = ['expense_date', 'expense_type', 'catalog_id', 'unit_id',
               'equipment_id', 'contractor_id', 'object_id',
               'quantity', 'unit_price', 'total_price', 'reason', 'comment', 'is_fine', 'batch_id']
    r = crud_create('expenses', data, allowed)
    if data.get('is_fine') and data.get('contractor_id'):
        execute('''INSERT INTO contractor_fines
                   (contractor_id, expense_id, equipment_id, fine_date, amount, reason, is_paid)
                   VALUES (?,?,?,?,?,?,0)''',
                (data['contractor_id'], r['id'], data.get('equipment_id'),
                 data.get('expense_date', datetime.now().strftime('%Y-%m-%d')),
                 data['total_price'], data.get('reason', '')))
    return jsonify(r), 201

@app.route('/api/expenses/<int:id>', methods=['GET', 'PUT', 'DELETE'])
def api_expense(id):
    if request.method == 'GET':
        r = query('''
            SELECT ex.*, uc.unified_name, u.short_name AS unit_name,
               e.serial_number AS equipment_sn, c.name AS contractor_name, o.name AS object_name
            FROM expenses ex
            LEFT JOIN unified_catalog uc ON ex.catalog_id=uc.id
            LEFT JOIN units u ON ex.unit_id=u.id
            LEFT JOIN equipment e ON ex.equipment_id=e.id
            LEFT JOIN contractors c ON ex.contractor_id=c.id
            LEFT JOIN objects o ON ex.object_id=o.id
            WHERE ex.id=?
        ''', (id,), one=True)
        return jsonify(r if r else ('Not found', 404))
    elif request.method == 'PUT':
        data = request.json
        if 'quantity' in data and 'unit_price' in data:
            data['total_price'] = round(data['quantity'] * data['unit_price'], 2)
        allowed = ['expense_date', 'expense_type', 'catalog_id', 'unit_id',
                   'equipment_id', 'contractor_id', 'object_id',
                   'quantity', 'unit_price', 'total_price', 'reason', 'comment', 'is_fine', 'batch_id']
        r = crud_update('expenses', id, data, allowed)
        return jsonify(r if r else ('Not found', 404))
    elif request.method == 'DELETE':
        execute('DELETE FROM contractor_fines WHERE expense_id=?', (id,))
        crud_delete('expenses', id)
        return jsonify({'ok': True})

# Fines
@app.route('/api/fines', methods=['GET'])
def api_fines_list():
    contractor_id = request.args.get('contractor_id', '')
    is_paid = request.args.get('is_paid', '')
    where = '1=1'
    params = []
    if contractor_id:
        where += ' AND cf.contractor_id=?'
        params.append(int(contractor_id))
    if is_paid != '':
        where += ' AND cf.is_paid=?'
        params.append(int(is_paid))
    sql = f'''
        SELECT cf.*, c.name AS contractor_name, e.serial_number AS equipment_sn
        FROM contractor_fines cf
        LEFT JOIN contractors c ON cf.contractor_id=c.id
        LEFT JOIN equipment e ON cf.equipment_id=e.id
        WHERE {where}
        ORDER BY cf.fine_date DESC
    '''
    return jsonify(query(sql, params))

@app.route('/api/fines/<int:id>', methods=['PUT'])
def api_fine_update(id):
    data = request.json
    if data.get('is_paid'):
        data['paid_date'] = datetime.now().strftime('%Y-%m-%d')
    r = crud_update('contractor_fines', id, data,
                    ['amount', 'reason', 'is_paid', 'paid_date'])
    return jsonify(r if r else ('Not found', 404))

# Stock
@app.route('/api/stock', methods=['GET'])
def api_stock():
    search = request.args.get('search', '')
    cat = request.args.get('category', '')
    low = request.args.get('low_stock', '')
    where = '1=1'
    params = []
    if search:
        pass  # filtered in Python below
    if cat:
        where += ' AND sv.category_name=?'
        params.append(cat)
    if low == '1':
        where += ' AND sv.quantity < sv.min_stock AND sv.min_stock > 0'
    sql = f'SELECT * FROM stock_view sv WHERE {where} ORDER BY sv.category_name, sv.unified_name'
    rows = query(sql, params)
    if search:
        s = search.lower()
        rows = [r for r in rows if s in (r.get('unified_name') or '').lower()]
    total_value = sum(r.get('total_value') or 0 for r in rows)
    total_items = sum(1 for r in rows if (r.get('quantity') or 0) > 0)
    return jsonify({
        'items': rows,
        'summary': {'total_items': total_items, 'total_value': round(total_value, 2)}
    })

# Stats
@app.route('/api/stats', methods=['GET'])
def api_stats():
    stats = {}
    stats['equipment_by_status'] = query(
        'SELECT status, COUNT(*) AS cnt FROM equipment GROUP BY status')
    stats['objects'] = query('''
        SELECT o.name, o.address,
               COUNT(e.id) AS equipment_count,
               GROUP_CONCAT(DISTINCT e.status) AS statuses
        FROM objects o
        LEFT JOIN equipment e ON e.current_object_id=o.id
        WHERE o.is_active=1
        GROUP BY o.id
        ORDER BY equipment_count DESC
    ''')
    stats['monthly_expenses'] = query('''
        SELECT strftime('%Y-%m', expense_date) AS month, expense_type,
               COUNT(*) AS cnt, ROUND(SUM(total_price), 2) AS total
        FROM expenses GROUP BY month, expense_type
        ORDER BY month DESC LIMIT 24
    ''')
    stats['monthly_receipts'] = query('''
        SELECT strftime('%Y-%m', receipt_date) AS month,
               COUNT(*) AS invoice_count, ROUND(SUM(total_amount), 2) AS total
        FROM receipts GROUP BY month ORDER BY month DESC LIMIT 12
    ''')
    stats['fines_summary'] = query('''
        SELECT c.name AS contractor_name, COUNT(cf.id) AS total_fines,
               SUM(CASE WHEN cf.is_paid=0 THEN cf.amount ELSE 0 END) AS unpaid,
               SUM(CASE WHEN cf.is_paid=1 THEN cf.amount ELSE 0 END) AS paid
        FROM contractor_fines cf
        JOIN contractors c ON cf.contractor_id=c.id
        GROUP BY cf.contractor_id ORDER BY unpaid DESC
    ''')
    stats['top_parts'] = query('''
        SELECT uc.unified_name, u.short_name AS unit_name,
               SUM(ex.quantity) AS total_qty, COUNT(ex.id) AS writeoff_count,
               ROUND(SUM(ex.total_price),2) AS total_cost
        FROM expenses ex
        JOIN unified_catalog uc ON ex.catalog_id=uc.id
        JOIN units u ON ex.unit_id=u.id
        GROUP BY ex.catalog_id ORDER BY total_qty DESC LIMIT 20
    ''')
    stats['recent_receipts'] = query('''
        SELECT r.receipt_date, s.name AS supplier_name,
               r.invoice_number, r.total_amount
        FROM receipts r LEFT JOIN suppliers s ON r.supplier_id=s.id
        ORDER BY r.receipt_date DESC LIMIT 10
    ''')
    stats['recent_expenses'] = query('''
        SELECT ex.expense_date, ex.expense_type, uc.unified_name,
               ex.quantity, ex.total_price, e.serial_number AS equipment_sn
        FROM expenses ex
        LEFT JOIN unified_catalog uc ON ex.catalog_id=uc.id
        LEFT JOIN equipment e ON ex.equipment_id=e.id
        ORDER BY ex.expense_date DESC LIMIT 10
    ''')
    return jsonify(stats)

# Import
@app.route('/api/import/equipment', methods=['POST'])
def api_import_equipment():
    data = request.json
    if not isinstance(data, list):
        return jsonify({'error': 'Expected JSON array'}), 400
    count = 0
    for item in data:
        try:
            execute('''INSERT OR IGNORE INTO equipment
                       (equipment_type, serial_number, inventory_number, status, notes)
                       VALUES (?,?,?,'in_stock',?)''',
                    (item.get('equipment_type', 'ZLP630'),
                     item['serial_number'], item.get('inventory_number', ''),
                     item.get('notes', '')))
            count += 1
        except Exception as e:
            print(f'Skip {item.get("serial_number")}: {e}')
    return jsonify({'imported': count})

# Kits
@app.route('/api/kits', methods=['POST'])
def api_kits_create():
    data = request.json
    items = data.pop('items', [])
    r = crud_create('equipment_kits', data,
        ['equipment_id', 'object_id', 'assembled_date', 'disassembled_date', 'height_meters', 'notes'])
    for item in items:
        execute('''INSERT INTO equipment_kit_items
                   (kit_id, catalog_id, quantity, length_meters, is_used, notes)
                   VALUES (?,?,?,?,?,?)''',
                (r['id'], item.get('catalog_id'), item.get('quantity', 1),
                 item.get('length_meters'), item.get('is_used', 0), item.get('notes', '')))
    return jsonify(r), 201

# Suggest
@app.route('/api/suggest-catalog', methods=['POST'])
def api_suggest_catalog():
    data = request.json
    item_name = data.get('item_name', '').strip()
    if not item_name:
        return jsonify([])
    sql = '''
        SELECT uc.id, uc.unified_name, c.name AS category_name, u.short_name AS unit_name,
               ca.alias_name, s.name AS supplier_name,
               CASE WHEN ca.alias_name IS NOT NULL THEN 1 ELSE 0 END AS has_alias
        FROM unified_catalog uc
        JOIN categories c ON uc.category_id=c.id
        JOIN units u ON uc.unit_id=u.id
        LEFT JOIN catalog_aliases ca ON ca.catalog_id=uc.id
        LEFT JOIN suppliers s ON ca.supplier_id=s.id
        ORDER BY has_alias DESC, uc.unified_name ASC
        LIMIT 30
    '''
    rows = query(sql)
    q = item_name.lower()
    rows = [r for r in rows if q in r['unified_name'].lower() or (r.get('alias_name') and q in r['alias_name'].lower())]
    return jsonify(rows[:10])

# Main


# ═══════════════ v10 NEW ENDPOINTS ═══════════════

# ─── Russian event type labels ───
EVENT_TYPE_RU = {
    'to': 'ТО', 'repair': 'Ремонт', 'assembly': 'Сборка',
    'disassembly': 'Разборка', 'move': 'Перемещение', 'inspection': 'Осмотр',
    'issue': 'Выдача', 'return': 'Возврат', 'other': 'Прочее'
}

# ─── Catalog detail (full history) ───
@app.route('/api/catalog/<int:id>/detail', methods=['GET'])
def api_catalog_detail(id):
    item = query('''
        SELECT uc.*, c.name AS category_name, u.short_name AS unit_name
        FROM unified_catalog uc
        JOIN categories c ON uc.category_id=c.id
        JOIN units u ON uc.unit_id=u.id
        WHERE uc.id=?
    ''', (id,), one=True)
    if not item:
        return jsonify('Not found'), 404
    item['aliases'] = query('''
        SELECT ca.*, s.name AS supplier_name
        FROM catalog_aliases ca LEFT JOIN suppliers s ON ca.supplier_id=s.id
        WHERE ca.catalog_id=?
    ''', (id,))
    item['receipts'] = query('''
        SELECT ri.*, r.receipt_date, r.invoice_number, s.name AS supplier_name
        FROM receipt_items ri
        JOIN receipts r ON ri.receipt_id=r.id
        LEFT JOIN suppliers s ON r.supplier_id=s.id
        WHERE ri.catalog_id=? ORDER BY r.receipt_date DESC LIMIT 50
    ''', (id,))
    item['expenses'] = query('''
        SELECT ex.*, e.serial_number AS equipment_sn, c.name AS contractor_name
        FROM expenses ex
        LEFT JOIN equipment e ON ex.equipment_id=e.id
        LEFT JOIN contractors c ON ex.contractor_id=c.id
        WHERE ex.catalog_id=? ORDER BY ex.expense_date DESC LIMIT 50
    ''', (id,))
    # Current stock
    item['stock'] = query('SELECT * FROM stock_view WHERE catalog_id=?', (id,), one=True)
    return jsonify(item)

# ─── Supplier detail ───
@app.route('/api/suppliers/<int:id>/detail', methods=['GET'])
def api_supplier_detail(id):
    s = crud_get('suppliers', id)
    if not s:
        return jsonify('Not found'), 404
    s['receipts'] = query('''
        SELECT r.*, COUNT(ri.id) AS item_count
        FROM receipts r LEFT JOIN receipt_items ri ON r.id=ri.receipt_id
        WHERE r.supplier_id=? GROUP BY r.id ORDER BY r.receipt_date DESC
    ''', (id,))
    s['aliases'] = query('''
        SELECT ca.*, uc.unified_name
        FROM catalog_aliases ca JOIN unified_catalog uc ON ca.catalog_id=uc.id
        WHERE ca.supplier_id=?
    ''', (id,))
    return jsonify(s)

# ─── Object detail ───
@app.route('/api/objects/<int:id>/detail', methods=['GET'])
def api_object_detail(id):
    obj = crud_get('objects', id)
    if not obj:
        return jsonify('Not found'), 404
    obj['equipment'] = query('''
        SELECT e.*, c.name AS contractor_name
        FROM equipment e LEFT JOIN contractors c ON e.current_contractor_id=c.id
        WHERE e.current_object_id=?
    ''', (id,))
    obj['contractors'] = query('''
        SELECT DISTINCT c.*, COUNT(e.id) AS eq_count
        FROM contractors c
        JOIN equipment e ON e.current_contractor_id=c.id
        WHERE e.current_object_id=?
        GROUP BY c.id
    ''', (id,))
    obj['repairs'] = query('''
        SELECT ex.*, uc.unified_name, u.short_name AS unit_name,
               e.serial_number AS equipment_sn, c.name AS contractor_name
        FROM expenses ex
        LEFT JOIN unified_catalog uc ON ex.catalog_id=uc.id
        LEFT JOIN units u ON ex.unit_id=u.id
        LEFT JOIN equipment e ON ex.equipment_id=e.id
        LEFT JOIN contractors c ON ex.contractor_id=c.id
        WHERE ex.object_id=? AND ex.expense_type IN ('to','repair','writeoff')
        ORDER BY ex.expense_date DESC LIMIT 100
    ''', (id,))
    obj['repair_stats'] = query('''
        SELECT COUNT(*) AS total_repairs,
               COALESCE(SUM(total_price), 0) AS total_cost
        FROM expenses WHERE object_id=? AND expense_type IN ('to','repair','writeoff')
    ''', (id,), one=True)
    return jsonify(obj)

# ─── Contractor detail ───
@app.route('/api/contractors/<int:id>/detail', methods=['GET'])
def api_contractor_detail(id):
    c = crud_get('contractors', id)
    if not c:
        return jsonify('Not found'), 404
    c['equipment'] = query('''
        SELECT e.*, o.name AS object_name
        FROM equipment e LEFT JOIN objects o ON e.current_object_id=o.id
        WHERE e.current_contractor_id=?
    ''', (id,))
    c['objects'] = query('''
        SELECT DISTINCT o.* FROM objects o
        JOIN equipment e ON e.current_object_id=o.id
        WHERE e.current_contractor_id=?
    ''', (id,))
    c['repairs'] = query('''
        SELECT ex.*, uc.unified_name, u.short_name AS unit_name,
               e.serial_number AS equipment_sn
        FROM expenses ex
        LEFT JOIN unified_catalog uc ON ex.catalog_id=uc.id
        LEFT JOIN units u ON ex.unit_id=u.id
        LEFT JOIN equipment e ON ex.equipment_id=e.id
        WHERE ex.contractor_id=? AND ex.expense_type IN ('to','repair','writeoff')
        ORDER BY ex.expense_date DESC LIMIT 100
    ''', (id,))
    c['fines'] = query('''
        SELECT cf.*, e.serial_number AS equipment_sn
        FROM contractor_fines cf LEFT JOIN equipment e ON cf.equipment_id=e.id
        WHERE cf.contractor_id=? ORDER BY cf.fine_date DESC
    ''', (id,))
    c['repair_stats'] = query('''
        SELECT COUNT(*) AS total_repairs,
               COALESCE(SUM(total_price), 0) AS total_cost
        FROM expenses WHERE contractor_id=? AND expense_type IN ('to','repair','writeoff')
    ''', (id,), one=True)
    c['unpaid_fines_total'] = query('''
        SELECT COALESCE(SUM(amount), 0) AS total FROM contractor_fines
        WHERE contractor_id=? AND is_paid=0
    ''', (id,), one=True)
    return jsonify(c)

# ─── Stock item detail ───
@app.route('/api/stock/<int:catalog_id>/detail', methods=['GET'])
def api_stock_detail(catalog_id):
    stock = query('SELECT * FROM stock_view WHERE catalog_id=?', (catalog_id,), one=True)
    if not stock:
        return jsonify('Not found'), 404
    stock['suppliers'] = query('''
        SELECT DISTINCT s.*, ca.alias_name
        FROM receipt_items ri
        JOIN receipts r ON ri.receipt_id=r.id
        JOIN suppliers s ON r.supplier_id=s.id
        LEFT JOIN catalog_aliases ca ON ca.catalog_id=ri.catalog_id AND ca.supplier_id=s.id
        WHERE ri.catalog_id=?
        ORDER BY s.name
    ''', (catalog_id,))
    stock['receipts'] = query('''
        SELECT ri.*, r.receipt_date, r.invoice_number, s.name AS supplier_name
        FROM receipt_items ri
        JOIN receipts r ON ri.receipt_id=r.id
        LEFT JOIN suppliers s ON r.supplier_id=s.id
        WHERE ri.catalog_id=? ORDER BY r.receipt_date DESC LIMIT 50
    ''', (catalog_id,))
    stock['expenses'] = query('''
        SELECT ex.*, e.serial_number AS equipment_sn, c.name AS contractor_name
        FROM expenses ex
        LEFT JOIN equipment e ON ex.equipment_id=e.id
        LEFT JOIN contractors c ON ex.contractor_id=c.id
        WHERE ex.catalog_id=? ORDER BY ex.expense_date DESC LIMIT 50
    ''', (catalog_id,))
    return jsonify(stock)

# ─── Equipment expense total ───
@app.route('/api/equipment/<int:id>/expenses-total', methods=['GET'])
def api_equipment_expenses_total(id):
    total = query('''
        SELECT COUNT(*) AS total_ops, COALESCE(SUM(total_price), 0) AS total_cost
        FROM expenses WHERE equipment_id=?
    ''', (id,), one=True)
    return jsonify(total)

# ─── Batch expense creation ───
@app.route('/api/expenses/batch', methods=['POST'])
def api_expenses_batch():
    data = request.json
    items = data.get('items', [])
    if not items:
        return jsonify({'error': 'No items'}), 400
    # Generate batch_id
    batch_id = int(datetime.now().timestamp() * 1000)
    results = []
    for item in items:
        item['batch_id'] = batch_id
        item['total_price'] = round(item.get('quantity', 0) * item.get('unit_price', 0), 2)
        allowed = ['expense_date', 'expense_type', 'catalog_id', 'unit_id',
                   'equipment_id', 'contractor_id', 'object_id',
                   'quantity', 'unit_price', 'total_price', 'reason', 'comment', 'is_fine', 'batch_id']
        r = crud_create('expenses', item, allowed)
        if item.get('is_fine') and item.get('contractor_id'):
            execute('''INSERT INTO contractor_fines
                       (contractor_id, expense_id, equipment_id, fine_date, amount, reason, is_paid)
                       VALUES (?,?,?,?,?,?,0)''',
                    (item['contractor_id'], r['id'], item.get('equipment_id'),
                     item.get('expense_date', datetime.now().strftime('%Y-%m-%d')),
                     item['total_price'], item.get('reason', '')))
        results.append(r)
    return jsonify({'batch_id': batch_id, 'items': results, 'count': len(results)}), 201

# ─── Fine validation (no new fine if unpaid) ───
@app.route('/api/fines', methods=['POST'])
def api_fines_create():
    data = request.json
    contractor_id = data.get('contractor_id')
    if contractor_id:
        unpaid = query('''
            SELECT COUNT(*) AS cnt FROM contractor_fines
            WHERE contractor_id=? AND is_paid=0
        ''', (contractor_id,), one=True)
        if unpaid and unpaid['cnt'] > 0:
            return jsonify({'error': 'У подрядчика есть неоплаченный штраф. Сначала оплатите старый.'}), 400
    r = crud_create('contractor_fines', data,
                    ['contractor_id', 'expense_id', 'equipment_id', 'fine_date', 'amount', 'reason', 'is_paid'])
    return jsonify(r), 201

# ─── Suggest catalog item with current avg price ───
@app.route('/api/catalog/suggest', methods=['GET'])
def api_catalog_suggest():
    q = request.args.get('q', '').strip().lower()
    cat = request.args.get('category', '')
    if not q:
        return jsonify([])
    where = '1=1'
    params = []
    if cat:
        where += ' AND c.name=?'
        params.append(cat)
    sql = f'''
        SELECT DISTINCT uc.id, uc.unified_name, c.name AS category_name,
               u.short_name AS unit_name, uc.unit_id,
               COALESCE(sv.weighted_avg_price, 0) AS avg_price,
               COALESCE(sv.quantity, 0) AS stock_qty
        FROM unified_catalog uc
        JOIN categories c ON uc.category_id=c.id
        JOIN units u ON uc.unit_id=u.id
        LEFT JOIN catalog_aliases ca ON ca.catalog_id=uc.id
        LEFT JOIN stock_view sv ON sv.catalog_id=uc.id
        WHERE {where}
        ORDER BY uc.unified_name ASC LIMIT 50
    '''
    rows = query(sql, params)
    # Filter in Python for Cyrillic case-insensitive search
    filtered = [r for r in rows if q in r['unified_name'].lower()]
    return jsonify(filtered[:15])

# ─── Equipment history in Russian ───
@app.route('/api/equipment/<int:eq_id>/history-ru', methods=['GET'])
def api_equipment_history_ru(eq_id):
    rows = query('''
        SELECT eh.*, o.name AS object_name, c.name AS contractor_name
        FROM equipment_history eh
        LEFT JOIN objects o ON eh.object_id=o.id
        LEFT JOIN contractors c ON eh.contractor_id=c.id
        WHERE eh.equipment_id=? ORDER BY eh.event_date DESC, eh.id DESC
    ''', (eq_id,))
    for r in rows:
        r['event_type_ru'] = EVENT_TYPE_RU.get(r['event_type'], r['event_type'])
    return jsonify(rows)


if __name__ == '__main__':
    init_db()
    print()
    print('=' * 60)
    print('  SKLAD v9 -- Spare Parts Inventory Management')
    print('  http://localhost:5150')
    print('=' * 60)
    print()
    app.run(host='0.0.0.0', port=5150, debug=True)


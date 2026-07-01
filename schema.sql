-- ============================================================
-- SKLAD v9 — Database Schema
-- Spare parts inventory for ZLP630 facade lifts
-- ============================================================

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- -------------------- UNITS --------------------
CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,       -- полное: штука, литр, метр
    short_name TEXT NOT NULL UNIQUE  -- краткое: шт, л, м
);

-- -------------------- CATEGORIES --------------------
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    sort_order INTEGER DEFAULT 0,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -------------------- SUPPLIERS --------------------
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    address TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    contact_person TEXT DEFAULT '',
    website TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -------------------- UNIFIED CATALOG --------------------
CREATE TABLE IF NOT EXISTS unified_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id),
    unified_name TEXT NOT NULL,
    unit_id INTEGER NOT NULL DEFAULT 1 REFERENCES units(id),
    description TEXT DEFAULT '',
    photo_path TEXT DEFAULT '',
    supplier_url TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    min_stock REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -------------------- CATALOG ALIASES --------------------
CREATE TABLE IF NOT EXISTS catalog_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_id INTEGER NOT NULL REFERENCES unified_catalog(id) ON DELETE CASCADE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    alias_name TEXT NOT NULL,
    UNIQUE(supplier_id, alias_name)
);

-- -------------------- OBJECTS (construction sites) --------------------
CREATE TABLE IF NOT EXISTS objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    address TEXT DEFAULT '',
    height_floors INTEGER,
    height_meters REAL,
    notes TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -------------------- CONTRACTORS (foremen) --------------------
CREATE TABLE IF NOT EXISTS contractors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT DEFAULT '',
    company TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -------------------- EQUIPMENT (ZLP630 lifts) --------------------
CREATE TABLE IF NOT EXISTS equipment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_type TEXT DEFAULT 'ZLP630',
    serial_number TEXT UNIQUE NOT NULL,
    inventory_number TEXT UNIQUE,
    status TEXT DEFAULT 'in_stock' CHECK(status IN ('in_stock','on_site','in_repair','decommissioned')),
    current_object_id INTEGER REFERENCES objects(id),
    current_contractor_id INTEGER REFERENCES contractors(id),
    notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -------------------- EQUIPMENT HISTORY --------------------
CREATE TABLE IF NOT EXISTS equipment_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id INTEGER NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK(event_type IN ('to','repair','assembly','disassembly','move','inspection','issue','return','other')),
    event_date DATE NOT NULL DEFAULT (date('now')),
    object_id INTEGER REFERENCES objects(id),
    contractor_id INTEGER REFERENCES contractors(id),
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -------------------- EQUIPMENT KITS --------------------
CREATE TABLE IF NOT EXISTS equipment_kits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id INTEGER NOT NULL REFERENCES equipment(id),
    object_id INTEGER REFERENCES objects(id),
    assembled_date DATE,
    disassembled_date DATE,
    height_meters REAL,
    notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -------------------- EQUIPMENT KIT ITEMS --------------------
CREATE TABLE IF NOT EXISTS equipment_kit_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kit_id INTEGER NOT NULL REFERENCES equipment_kits(id) ON DELETE CASCADE,
    catalog_id INTEGER REFERENCES unified_catalog(id),
    quantity REAL NOT NULL DEFAULT 1,
    length_meters REAL,
    is_used INTEGER DEFAULT 0,   -- 0=new from stock, 1=used from other sites
    notes TEXT DEFAULT ''
);

-- -------------------- RECEIPTS (incoming invoices) --------------------
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    receipt_date DATE NOT NULL DEFAULT (date('now')),
    invoice_number TEXT DEFAULT '',
    status TEXT DEFAULT 'received' CHECK(status IN ('paid','received')),
    comment TEXT DEFAULT '',
    total_amount REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -------------------- RECEIPT ITEMS --------------------
CREATE TABLE IF NOT EXISTS receipt_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    catalog_id INTEGER REFERENCES unified_catalog(id),
    item_name TEXT NOT NULL,
    category_id INTEGER REFERENCES categories(id),
    unit_id INTEGER DEFAULT 1 REFERENCES units(id),
    quantity REAL NOT NULL,
    unit_price REAL NOT NULL,
    total_price REAL NOT NULL,
    comment TEXT DEFAULT ''
);

-- -------------------- EXPENSES (write-offs) --------------------
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_date DATE NOT NULL DEFAULT (date('now')),
    expense_type TEXT NOT NULL CHECK(expense_type IN ('to','repair','writeoff')),
    catalog_id INTEGER REFERENCES unified_catalog(id),
    unit_id INTEGER DEFAULT 1 REFERENCES units(id),
    equipment_id INTEGER REFERENCES equipment(id),
    contractor_id INTEGER REFERENCES contractors(id),
    object_id INTEGER REFERENCES objects(id),
    quantity REAL NOT NULL,
    unit_price REAL NOT NULL,
    total_price REAL NOT NULL,
    reason TEXT DEFAULT '',
    comment TEXT DEFAULT '',
    is_fine INTEGER DEFAULT 0,
    batch_id INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -------------------- CONTRACTOR FINES --------------------
CREATE TABLE IF NOT EXISTS contractor_fines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contractor_id INTEGER NOT NULL REFERENCES contractors(id),
    expense_id INTEGER REFERENCES expenses(id),
    equipment_id INTEGER REFERENCES equipment(id),
    fine_date DATE NOT NULL DEFAULT (date('now')),
    amount REAL NOT NULL,
    reason TEXT DEFAULT '',
    is_paid INTEGER DEFAULT 0,
    paid_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- -------------------- INDEXES --------------------
CREATE INDEX IF NOT EXISTS idx_uc_category ON unified_catalog(category_id);
CREATE INDEX IF NOT EXISTS idx_aliases_catalog ON catalog_aliases(catalog_id);
CREATE INDEX IF NOT EXISTS idx_aliases_supplier ON catalog_aliases(supplier_id);
CREATE INDEX IF NOT EXISTS idx_ri_receipt ON receipt_items(receipt_id);
CREATE INDEX IF NOT EXISTS idx_ri_catalog ON receipt_items(catalog_id);
CREATE INDEX IF NOT EXISTS idx_exp_catalog ON expenses(catalog_id);
CREATE INDEX IF NOT EXISTS idx_exp_equipment ON expenses(equipment_id);
CREATE INDEX IF NOT EXISTS idx_exp_contractor ON expenses(contractor_id);
CREATE INDEX IF NOT EXISTS idx_exp_type ON expenses(expense_type);
CREATE INDEX IF NOT EXISTS idx_eq_status ON equipment(status);
CREATE INDEX IF NOT EXISTS idx_eq_object ON equipment(current_object_id);
CREATE INDEX IF NOT EXISTS idx_eqh_equipment ON equipment_history(equipment_id);
CREATE INDEX IF NOT EXISTS idx_eqh_date ON equipment_history(event_date);
CREATE INDEX IF NOT EXISTS idx_fines_contractor ON contractor_fines(contractor_id);

-- -------------------- STOCK VIEW --------------------
DROP VIEW IF EXISTS stock_view;
CREATE VIEW stock_view AS
SELECT 
    uc.id AS catalog_id,
    uc.unified_name,
    c.name AS category_name,
    u.short_name AS unit_name,
    COALESCE(ri.total_qty, 0) AS total_received,
    COALESCE(ex.total_qty, 0) AS total_spent,
    COALESCE(ri.total_qty, 0) - COALESCE(ex.total_qty, 0) AS quantity,
    CASE 
        WHEN COALESCE(ri.total_qty, 0) > 0 
        THEN ROUND(COALESCE(ri.total_value, 0) / ri.total_qty, 2)
        ELSE 0 
    END AS weighted_avg_price,
    ROUND((COALESCE(ri.total_qty, 0) - COALESCE(ex.total_qty, 0)) * 
    CASE 
        WHEN COALESCE(ri.total_qty, 0) > 0 
        THEN COALESCE(ri.total_value, 0) / ri.total_qty
        ELSE 0 
    END, 2) AS total_value,
    uc.min_stock,
    uc.category_id,
    uc.unit_id
FROM unified_catalog uc
JOIN categories c ON uc.category_id = c.id
JOIN units u ON uc.unit_id = u.id
LEFT JOIN (
    SELECT ri.catalog_id, SUM(ri.quantity) AS total_qty, SUM(ri.total_price) AS total_value
    FROM receipt_items ri
    JOIN receipts r ON ri.receipt_id = r.id
    WHERE r.status = 'received' AND ri.catalog_id IS NOT NULL
    GROUP BY ri.catalog_id
) ri ON uc.id = ri.catalog_id
LEFT JOIN (
    SELECT catalog_id, SUM(quantity) AS total_qty
    FROM expenses WHERE catalog_id IS NOT NULL
    GROUP BY catalog_id
) ex ON uc.id = ex.catalog_id;

-- -------------------- SEED DATA --------------------
INSERT OR IGNORE INTO units (name, short_name) VALUES
    ('штука', 'шт'),
    ('литр', 'л'),
    ('метр', 'м'),
    ('килограмм', 'кг'),
    ('комплект', 'компл'),
    ('пара', 'пар'),
    ('упаковка', 'уп'),
    ('рулон', 'рул'),
    ('грамм', 'г'),
    ('канистра', 'кан');

INSERT OR IGNORE INTO categories (name, sort_order, description) VALUES
    ('ZLP', 1, 'Запчасти для фасадных подъемников ZLP630'),
    ('Метизы', 2, 'Крепеж, болты, гайки, шайбы'),
    ('Металл', 3, 'Металлопрокат, листы, профиль'),
    ('Покраска', 4, 'Краски, грунтовки, растворители'),
    ('Эл. товары', 5, 'Электрика, кабели, кнопки, автоматы'),
    ('Хоз. товары', 6, 'Хозяйственные товары, инвентарь'),
    ('Прочее', 99, 'Всё остальное');

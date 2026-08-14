-- Wes Vendor Portal — Database Schema (Supabase PostgreSQL)
-- Run this directly against your Supabase PostgreSQL, or use as reference for Alembic migrations.

-- User profiles (linked to Supabase auth.users via id)
CREATE TABLE IF NOT EXISTS user_profiles (
    id VARCHAR(36) PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(30) NOT NULL DEFAULT 'requester' CHECK (role IN ('requester','purchase_person','management','admin')),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Vendor categories / groups
CREATE TABLE IF NOT EXISTS categories (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    description VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Vendors
CREATE TABLE IF NOT EXISTS vendors (
    id VARCHAR(36) PRIMARY KEY,
    company_name VARCHAR(255) NOT NULL,
    contact_email VARCHAR(255) NOT NULL,
    contact_person VARCHAR(255),
    phone VARCHAR(50),
    notes VARCHAR(1000),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Vendor ↔ Category join table
CREATE TABLE IF NOT EXISTS vendor_categories (
    vendor_id VARCHAR(36) REFERENCES vendors(id) ON DELETE CASCADE,
    category_id VARCHAR(36) REFERENCES categories(id) ON DELETE CASCADE,
    PRIMARY KEY (vendor_id, category_id)
);

-- Requisitions
CREATE TABLE IF NOT EXISTS requisitions (
    id VARCHAR(36) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    item_description TEXT NOT NULL,
    quantity NUMERIC NOT NULL,
    unit VARCHAR(50),
    notes TEXT,
    status VARCHAR(20) DEFAULT 'draft' CHECK (status IN ('draft','sent','received','reviewed','decided','completed')),
    created_by VARCHAR(36) REFERENCES user_profiles(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Requisition ↔ Vendor links (unique link per vendor per requisition)
CREATE TABLE IF NOT EXISTS requisition_vendors (
    id VARCHAR(36) PRIMARY KEY,
    requisition_id VARCHAR(36) REFERENCES requisitions(id) ON DELETE CASCADE,
    vendor_id VARCHAR(36) REFERENCES vendors(id) ON DELETE CASCADE,
    unique_link_token VARCHAR(36) UNIQUE NOT NULL,
    link_sent_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending','submitted','flagged','accepted')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (requisition_id, vendor_id)
);

-- Quotations (one per requisition_vendor)
CREATE TABLE IF NOT EXISTS quotations (
    id VARCHAR(36) PRIMARY KEY,
    requisition_vendor_id VARCHAR(36) REFERENCES requisition_vendors(id) ON DELETE CASCADE UNIQUE,
    submission_type VARCHAR(10) NOT NULL CHECK (submission_type IN ('image','form')),
    image_url VARCHAR(500),
    form_data JSONB,
    submitted_at TIMESTAMPTZ DEFAULT NOW(),
    notes TEXT
);

-- Decisions
CREATE TABLE IF NOT EXISTS decisions (
    id VARCHAR(36) PRIMARY KEY,
    requisition_id VARCHAR(36) REFERENCES requisitions(id) ON DELETE CASCADE,
    winning_vendor_id VARCHAR(36) REFERENCES vendors(id),
    decided_by VARCHAR(36) REFERENCES user_profiles(id),
    decided_at TIMESTAMPTZ DEFAULT NOW(),
    notes TEXT,
    management_approved BOOLEAN,
    approved_by VARCHAR(36) REFERENCES user_profiles(id),
    approved_at TIMESTAMPTZ
);

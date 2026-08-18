
CREATE TYPE public.lead_status AS ENUM ('new','qualified','proposal','negotiation','won','lost','on_hold');
CREATE TYPE public.quotation_status AS ENUM ('draft','submitted','approved','rejected','sent','won','lost','expired');
CREATE TYPE public.project_status AS ENUM ('planning','active','on_hold','completed','archived','cancelled');
CREATE TYPE public.contract_status AS ENUM ('draft','active','suspended','completed','terminated');
CREATE TYPE public.po_status AS ENUM ('draft','pending_approval','approved','rejected','partially_received','received','cancelled');
CREATE TYPE public.invoice_status AS ENUM ('draft','issued','partially_paid','paid','overdue','cancelled');
CREATE TYPE public.invoice_type AS ENUM ('sales','purchase');
CREATE TYPE public.approval_status AS ENUM ('pending','approved','rejected');
CREATE TYPE public.doc_status AS ENUM ('draft','pending_approval','approved','rejected','superseded');

-- ===== settings & numbering =====
CREATE TABLE public.company_settings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_name TEXT NOT NULL DEFAULT 'Vision Contracting Co.',
  company_name_ar TEXT NOT NULL DEFAULT 'شركة الرؤية للمقاولات',
  vat_number TEXT,
  cr_number TEXT,
  address TEXT,
  city TEXT DEFAULT 'Riyadh',
  phone TEXT,
  email TEXT,
  default_vat_rate NUMERIC(5,2) NOT NULL DEFAULT 15,
  currency TEXT NOT NULL DEFAULT 'SAR',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO public.company_settings (vat_number, cr_number, city) VALUES ('300000000000003','1010000000','Riyadh');

CREATE TABLE public.doc_counters (
  prefix TEXT NOT NULL,
  year INT NOT NULL,
  last_value INT NOT NULL DEFAULT 0,
  PRIMARY KEY (prefix, year)
);

CREATE OR REPLACE FUNCTION public.next_doc_number(_prefix TEXT)
RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE y INT := EXTRACT(YEAR FROM now())::INT; v INT;
BEGIN
  INSERT INTO public.doc_counters (prefix, year, last_value) VALUES (_prefix, y, 1)
  ON CONFLICT (prefix, year) DO UPDATE SET last_value = public.doc_counters.last_value + 1
  RETURNING last_value INTO v;
  RETURN _prefix || '-' || y || '-' || lpad(v::TEXT, 4, '0');
END; $$;

-- ===== CRM =====
CREATE TABLE public.customers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT,
  name TEXT NOT NULL,
  name_ar TEXT,
  vat_number TEXT,
  cr_number TEXT,
  industry TEXT,
  address TEXT,
  city TEXT,
  region TEXT,
  country TEXT NOT NULL DEFAULT 'Saudi Arabia',
  phone TEXT,
  email TEXT,
  website TEXT,
  payment_terms_days INT NOT NULL DEFAULT 30,
  credit_limit NUMERIC(14,2) NOT NULL DEFAULT 0,
  owner_id UUID,
  status TEXT NOT NULL DEFAULT 'active',
  notes TEXT,
  created_by UUID DEFAULT auth.uid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.contacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id UUID REFERENCES public.customers ON DELETE CASCADE,
  name TEXT NOT NULL,
  name_ar TEXT,
  position TEXT,
  email TEXT,
  phone TEXT,
  mobile TEXT,
  is_primary BOOLEAN NOT NULL DEFAULT false,
  notes TEXT,
  created_by UUID DEFAULT auth.uid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.leads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  customer_id UUID REFERENCES public.customers ON DELETE SET NULL,
  contact_id UUID REFERENCES public.contacts ON DELETE SET NULL,
  source TEXT,
  status public.lead_status NOT NULL DEFAULT 'new',
  estimated_value NUMERIC(14,2) NOT NULL DEFAULT 0,
  probability INT NOT NULL DEFAULT 20,
  expected_close_date DATE,
  assigned_to UUID,
  description TEXT,
  close_reason TEXT,
  closed_at TIMESTAMPTZ,
  created_by UUID DEFAULT auth.uid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===== QUOTATIONS =====
CREATE TABLE public.quotations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  quote_no TEXT NOT NULL UNIQUE DEFAULT public.next_doc_number('QT'),
  title TEXT NOT NULL,
  customer_id UUID REFERENCES public.customers ON DELETE SET NULL,
  lead_id UUID REFERENCES public.leads ON DELETE SET NULL,
  scope TEXT,
  currency TEXT NOT NULL DEFAULT 'SAR',
  issue_date DATE NOT NULL DEFAULT CURRENT_DATE,
  valid_until DATE,
  subtotal NUMERIC(14,2) NOT NULL DEFAULT 0,
  discount_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
  vat_rate NUMERIC(5,2) NOT NULL DEFAULT 15,
  vat_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
  total NUMERIC(14,2) NOT NULL DEFAULT 0,
  status public.quotation_status NOT NULL DEFAULT 'draft',
  terms TEXT,
  notes TEXT,
  owner_id UUID DEFAULT auth.uid(),
  created_by UUID DEFAULT auth.uid(),
  submitted_by UUID,
  submitted_at TIMESTAMPTZ,
  approved_by UUID,
  approved_at TIMESTAMPTZ,
  rejected_by UUID,
  rejected_at TIMESTAMPTZ,
  rejection_reason TEXT,
  sent_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.quotation_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  quotation_id UUID NOT NULL REFERENCES public.quotations ON DELETE CASCADE,
  line_no INT NOT NULL DEFAULT 1,
  description TEXT NOT NULL,
  unit TEXT NOT NULL DEFAULT 'no',
  quantity NUMERIC(14,3) NOT NULL DEFAULT 1,
  unit_price NUMERIC(14,2) NOT NULL DEFAULT 0,
  line_total NUMERIC(14,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.quotation_approvals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  quotation_id UUID NOT NULL REFERENCES public.quotations ON DELETE CASCADE,
  action TEXT NOT NULL,
  actor_id UUID NOT NULL DEFAULT auth.uid(),
  comment TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===== PROJECTS / CONTRACTS =====
CREATE TABLE public.projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT NOT NULL UNIQUE DEFAULT public.next_doc_number('PRJ'),
  name TEXT NOT NULL,
  name_ar TEXT,
  customer_id UUID REFERENCES public.customers ON DELETE SET NULL,
  quotation_id UUID REFERENCES public.quotations ON DELETE SET NULL,
  project_manager_id UUID,
  status public.project_status NOT NULL DEFAULT 'planning',
  start_date DATE,
  end_date DATE,
  contract_value NUMERIC(14,2) NOT NULL DEFAULT 0,
  progress_percent INT NOT NULL DEFAULT 0,
  location TEXT,
  description TEXT,
  created_by UUID DEFAULT auth.uid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.project_members (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES public.projects ON DELETE CASCADE,
  user_id UUID NOT NULL,
  role_label TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, user_id)
);

CREATE TABLE public.contracts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_no TEXT NOT NULL UNIQUE DEFAULT public.next_doc_number('CNT'),
  title TEXT NOT NULL,
  project_id UUID REFERENCES public.projects ON DELETE SET NULL,
  customer_id UUID REFERENCES public.customers ON DELETE SET NULL,
  value NUMERIC(14,2) NOT NULL DEFAULT 0,
  vat_rate NUMERIC(5,2) NOT NULL DEFAULT 15,
  retention_percent NUMERIC(5,2) NOT NULL DEFAULT 5,
  signed_date DATE,
  start_date DATE,
  end_date DATE,
  status public.contract_status NOT NULL DEFAULT 'draft',
  terms TEXT,
  created_by UUID DEFAULT auth.uid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===== PROCUREMENT =====
CREATE TABLE public.suppliers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT,
  name TEXT NOT NULL,
  name_ar TEXT,
  vat_number TEXT,
  cr_number TEXT,
  category TEXT,
  contact_name TEXT,
  email TEXT,
  phone TEXT,
  address TEXT,
  city TEXT,
  rating INT NOT NULL DEFAULT 3,
  payment_terms_days INT NOT NULL DEFAULT 30,
  status TEXT NOT NULL DEFAULT 'active',
  notes TEXT,
  created_by UUID DEFAULT auth.uid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.purchase_orders (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  po_no TEXT NOT NULL UNIQUE DEFAULT public.next_doc_number('PO'),
  supplier_id UUID REFERENCES public.suppliers ON DELETE SET NULL,
  project_id UUID REFERENCES public.projects ON DELETE SET NULL,
  status public.po_status NOT NULL DEFAULT 'draft',
  order_date DATE NOT NULL DEFAULT CURRENT_DATE,
  expected_delivery DATE,
  currency TEXT NOT NULL DEFAULT 'SAR',
  subtotal NUMERIC(14,2) NOT NULL DEFAULT 0,
  vat_rate NUMERIC(5,2) NOT NULL DEFAULT 15,
  vat_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
  total NUMERIC(14,2) NOT NULL DEFAULT 0,
  notes TEXT,
  created_by UUID DEFAULT auth.uid(),
  submitted_at TIMESTAMPTZ,
  approved_by UUID,
  approved_at TIMESTAMPTZ,
  received_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.purchase_order_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  purchase_order_id UUID NOT NULL REFERENCES public.purchase_orders ON DELETE CASCADE,
  line_no INT NOT NULL DEFAULT 1,
  description TEXT NOT NULL,
  unit TEXT NOT NULL DEFAULT 'no',
  quantity NUMERIC(14,3) NOT NULL DEFAULT 1,
  unit_price NUMERIC(14,2) NOT NULL DEFAULT 0,
  received_quantity NUMERIC(14,3) NOT NULL DEFAULT 0,
  line_total NUMERIC(14,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===== FINANCE =====
CREATE TABLE public.invoices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_no TEXT NOT NULL UNIQUE DEFAULT public.next_doc_number('INV'),
  type public.invoice_type NOT NULL DEFAULT 'sales',
  customer_id UUID REFERENCES public.customers ON DELETE SET NULL,
  supplier_id UUID REFERENCES public.suppliers ON DELETE SET NULL,
  project_id UUID REFERENCES public.projects ON DELETE SET NULL,
  contract_id UUID REFERENCES public.contracts ON DELETE SET NULL,
  purchase_order_id UUID REFERENCES public.purchase_orders ON DELETE SET NULL,
  issue_date DATE NOT NULL DEFAULT CURRENT_DATE,
  due_date DATE,
  currency TEXT NOT NULL DEFAULT 'SAR',
  subtotal NUMERIC(14,2) NOT NULL DEFAULT 0,
  vat_rate NUMERIC(5,2) NOT NULL DEFAULT 15,
  vat_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
  total NUMERIC(14,2) NOT NULL DEFAULT 0,
  amount_paid NUMERIC(14,2) NOT NULL DEFAULT 0,
  status public.invoice_status NOT NULL DEFAULT 'draft',
  notes TEXT,
  created_by UUID DEFAULT auth.uid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.invoice_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_id UUID NOT NULL REFERENCES public.invoices ON DELETE CASCADE,
  line_no INT NOT NULL DEFAULT 1,
  description TEXT NOT NULL,
  unit TEXT NOT NULL DEFAULT 'no',
  quantity NUMERIC(14,3) NOT NULL DEFAULT 1,
  unit_price NUMERIC(14,2) NOT NULL DEFAULT 0,
  line_total NUMERIC(14,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.payments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_id UUID NOT NULL REFERENCES public.invoices ON DELETE CASCADE,
  amount NUMERIC(14,2) NOT NULL,
  payment_date DATE NOT NULL DEFAULT CURRENT_DATE,
  method TEXT NOT NULL DEFAULT 'bank_transfer',
  reference TEXT,
  notes TEXT,
  recorded_by UUID NOT NULL DEFAULT auth.uid(),
  approved_by UUID,
  approved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.expenses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES public.projects ON DELETE SET NULL,
  category TEXT NOT NULL DEFAULT 'general',
  description TEXT NOT NULL,
  amount NUMERIC(14,2) NOT NULL DEFAULT 0,
  vat_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
  expense_date DATE NOT NULL DEFAULT CURRENT_DATE,
  status public.approval_status NOT NULL DEFAULT 'pending',
  submitted_by UUID NOT NULL DEFAULT auth.uid(),
  approved_by UUID,
  approved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===== DOCUMENTS =====
CREATE TABLE public.documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'general',
  entity_type TEXT,
  entity_id UUID,
  project_id UUID REFERENCES public.projects ON DELETE SET NULL,
  storage_path TEXT NOT NULL,
  file_name TEXT,
  mime_type TEXT,
  size_bytes BIGINT,
  version INT NOT NULL DEFAULT 1,
  supersedes_id UUID REFERENCES public.documents ON DELETE SET NULL,
  status public.doc_status NOT NULL DEFAULT 'draft',
  uploaded_by UUID NOT NULL DEFAULT auth.uid(),
  approved_by UUID,
  approved_at TIMESTAMPTZ,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===== updated_at triggers =====
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['customers','contacts','leads','quotations','projects','contracts','suppliers','purchase_orders','invoices','expenses','documents']
  LOOP
    EXECUTE format('CREATE TRIGGER trg_%s_updated BEFORE UPDATE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();', t, t);
  END LOOP;
END $$;

-- ===== SEPARATION OF DUTIES =====
CREATE OR REPLACE FUNCTION public.enforce_quotation_sod()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  IF NEW.approved_by IS NOT NULL AND (NEW.approved_by = COALESCE(NEW.created_by, '00000000-0000-0000-0000-000000000000') OR NEW.approved_by = COALESCE(NEW.submitted_by, '00000000-0000-0000-0000-000000000000')) THEN
    RAISE EXCEPTION 'Separation of duties: you cannot approve a quotation you created or submitted';
  END IF;
  IF NEW.rejected_by IS NOT NULL AND NEW.rejected_by = COALESCE(NEW.created_by, '00000000-0000-0000-0000-000000000000') THEN
    RAISE EXCEPTION 'Separation of duties: you cannot reject your own quotation';
  END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER trg_quotation_sod BEFORE INSERT OR UPDATE ON public.quotations
FOR EACH ROW EXECUTE FUNCTION public.enforce_quotation_sod();

CREATE OR REPLACE FUNCTION public.enforce_po_sod()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  IF NEW.approved_by IS NOT NULL AND NEW.approved_by = COALESCE(NEW.created_by, '00000000-0000-0000-0000-000000000000') THEN
    RAISE EXCEPTION 'Separation of duties: you cannot approve a purchase order you created';
  END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER trg_po_sod BEFORE INSERT OR UPDATE ON public.purchase_orders
FOR EACH ROW EXECUTE FUNCTION public.enforce_po_sod();

CREATE OR REPLACE FUNCTION public.enforce_expense_sod()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  IF NEW.approved_by IS NOT NULL AND NEW.approved_by = NEW.submitted_by THEN
    RAISE EXCEPTION 'Separation of duties: you cannot approve your own expense';
  END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER trg_expense_sod BEFORE INSERT OR UPDATE ON public.expenses
FOR EACH ROW EXECUTE FUNCTION public.enforce_expense_sod();

CREATE OR REPLACE FUNCTION public.enforce_payment_sod()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  IF NEW.approved_by IS NOT NULL AND NEW.approved_by = NEW.recorded_by THEN
    RAISE EXCEPTION 'Separation of duties: you cannot approve a payment you recorded';
  END IF;
  RETURN NEW;
END; $$;
CREATE TRIGGER trg_payment_sod BEFORE INSERT OR UPDATE ON public.payments
FOR EACH ROW EXECUTE FUNCTION public.enforce_payment_sod();

-- keep invoice amount_paid in sync
CREATE OR REPLACE FUNCTION public.sync_invoice_paid()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE inv UUID; paid NUMERIC(14,2); tot NUMERIC(14,2);
BEGIN
  inv := COALESCE(NEW.invoice_id, OLD.invoice_id);
  SELECT COALESCE(SUM(amount),0) INTO paid FROM public.payments WHERE invoice_id = inv;
  SELECT total INTO tot FROM public.invoices WHERE id = inv;
  UPDATE public.invoices SET amount_paid = paid,
    status = CASE WHEN paid >= tot AND tot > 0 THEN 'paid'::public.invoice_status
                  WHEN paid > 0 THEN 'partially_paid'::public.invoice_status
                  ELSE status END
  WHERE id = inv;
  RETURN NULL;
END; $$;
CREATE TRIGGER trg_payments_sync AFTER INSERT OR UPDATE OR DELETE ON public.payments
FOR EACH ROW EXECUTE FUNCTION public.sync_invoice_paid();

-- project membership helper
CREATE OR REPLACE FUNCTION public.is_project_member(_project_id UUID, _user_id UUID)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.project_members WHERE project_id = _project_id AND user_id = _user_id)
      OR EXISTS (SELECT 1 FROM public.projects WHERE id = _project_id AND project_manager_id = _user_id);
$$;

-- ===== GRANTS =====
GRANT SELECT, INSERT, UPDATE, DELETE ON
  public.customers, public.contacts, public.leads, public.quotations, public.quotation_items,
  public.quotation_approvals, public.projects, public.project_members, public.contracts,
  public.suppliers, public.purchase_orders, public.purchase_order_items, public.invoices,
  public.invoice_items, public.payments, public.expenses, public.documents,
  public.company_settings TO authenticated;
GRANT SELECT ON public.doc_counters TO authenticated;
GRANT ALL ON public.customers, public.contacts, public.leads, public.quotations, public.quotation_items,
  public.quotation_approvals, public.projects, public.project_members, public.contracts,
  public.suppliers, public.purchase_orders, public.purchase_order_items, public.invoices,
  public.invoice_items, public.payments, public.expenses, public.documents,
  public.company_settings, public.doc_counters TO service_role;

-- ===== RLS =====
ALTER TABLE public.customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quotations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quotation_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quotation_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.project_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.suppliers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.purchase_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.purchase_order_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.expenses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.company_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.doc_counters ENABLE ROW LEVEL SECURITY;

-- customers
CREATE POLICY "customers_select" ON public.customers FOR SELECT TO authenticated
  USING (public.can('customers.view') AND (public.has_full_scope() OR owner_id = auth.uid() OR created_by = auth.uid()));
CREATE POLICY "customers_insert" ON public.customers FOR INSERT TO authenticated
  WITH CHECK (public.can('customers.create'));
CREATE POLICY "customers_update" ON public.customers FOR UPDATE TO authenticated
  USING (public.can('customers.edit') AND (public.has_full_scope() OR owner_id = auth.uid() OR created_by = auth.uid()))
  WITH CHECK (public.can('customers.edit'));
CREATE POLICY "customers_delete" ON public.customers FOR DELETE TO authenticated
  USING (public.can('customers.delete'));

-- contacts
CREATE POLICY "contacts_select" ON public.contacts FOR SELECT TO authenticated USING (public.can('contacts.view'));
CREATE POLICY "contacts_insert" ON public.contacts FOR INSERT TO authenticated WITH CHECK (public.can('contacts.create'));
CREATE POLICY "contacts_update" ON public.contacts FOR UPDATE TO authenticated
  USING (public.can('contacts.edit')) WITH CHECK (public.can('contacts.edit'));
CREATE POLICY "contacts_delete" ON public.contacts FOR DELETE TO authenticated USING (public.can('contacts.delete'));

-- leads
CREATE POLICY "leads_select" ON public.leads FOR SELECT TO authenticated
  USING (public.can('leads.view') AND (public.has_full_scope() OR assigned_to = auth.uid() OR created_by = auth.uid()));
CREATE POLICY "leads_insert" ON public.leads FOR INSERT TO authenticated WITH CHECK (public.can('leads.create'));
CREATE POLICY "leads_update" ON public.leads FOR UPDATE TO authenticated
  USING (public.can('leads.edit') AND (public.has_full_scope() OR assigned_to = auth.uid() OR created_by = auth.uid()))
  WITH CHECK (public.can('leads.edit'));
CREATE POLICY "leads_delete" ON public.leads FOR DELETE TO authenticated USING (public.can('admin.settings'));

-- quotations
CREATE POLICY "quotations_select" ON public.quotations FOR SELECT TO authenticated
  USING (public.can('quotations.view') AND (public.has_full_scope() OR owner_id = auth.uid() OR created_by = auth.uid() OR public.can('quotations.approve')));
CREATE POLICY "quotations_insert" ON public.quotations FOR INSERT TO authenticated WITH CHECK (public.can('quotations.create'));
CREATE POLICY "quotations_update" ON public.quotations FOR UPDATE TO authenticated
  USING (
    (public.can('quotations.edit') AND status IN ('draft','rejected') AND (public.has_full_scope() OR owner_id = auth.uid() OR created_by = auth.uid()))
    OR (public.can('quotations.submit') AND (owner_id = auth.uid() OR created_by = auth.uid()))
    OR public.can('quotations.approve') OR public.can('quotations.reject') OR public.can('quotations.send')
  )
  WITH CHECK (public.can('quotations.edit') OR public.can('quotations.submit') OR public.can('quotations.approve') OR public.can('quotations.reject') OR public.can('quotations.send'));
CREATE POLICY "quotations_delete" ON public.quotations FOR DELETE TO authenticated USING (public.can('quotations.delete'));

CREATE POLICY "quotation_items_all" ON public.quotation_items FOR ALL TO authenticated
  USING (EXISTS (SELECT 1 FROM public.quotations q WHERE q.id = quotation_id))
  WITH CHECK (public.can('quotations.create') OR public.can('quotations.edit'));

CREATE POLICY "quotation_approvals_select" ON public.quotation_approvals FOR SELECT TO authenticated
  USING (public.can('quotations.view'));
CREATE POLICY "quotation_approvals_insert" ON public.quotation_approvals FOR INSERT TO authenticated
  WITH CHECK (actor_id = auth.uid() AND public.can('quotations.view'));

-- projects
CREATE POLICY "projects_select" ON public.projects FOR SELECT TO authenticated
  USING (public.can('projects.view') AND (public.has_full_scope() OR public.is_project_member(id, auth.uid()) OR created_by = auth.uid()));
CREATE POLICY "projects_insert" ON public.projects FOR INSERT TO authenticated WITH CHECK (public.can('projects.create'));
CREATE POLICY "projects_update" ON public.projects FOR UPDATE TO authenticated
  USING (public.can('projects.edit') AND (public.has_full_scope() OR public.is_project_member(id, auth.uid())))
  WITH CHECK (public.can('projects.edit'));
CREATE POLICY "projects_delete" ON public.projects FOR DELETE TO authenticated USING (public.can('projects.archive'));

CREATE POLICY "project_members_select" ON public.project_members FOR SELECT TO authenticated USING (public.can('projects.view'));
CREATE POLICY "project_members_manage" ON public.project_members FOR ALL TO authenticated
  USING (public.can('projects.edit')) WITH CHECK (public.can('projects.edit'));

-- contracts
CREATE POLICY "contracts_select" ON public.contracts FOR SELECT TO authenticated USING (public.can('contracts.view'));
CREATE POLICY "contracts_insert" ON public.contracts FOR INSERT TO authenticated WITH CHECK (public.can('contracts.create'));
CREATE POLICY "contracts_update" ON public.contracts FOR UPDATE TO authenticated
  USING (public.can('contracts.edit')) WITH CHECK (public.can('contracts.edit'));
CREATE POLICY "contracts_delete" ON public.contracts FOR DELETE TO authenticated USING (public.can('contracts.delete'));

-- suppliers
CREATE POLICY "suppliers_select" ON public.suppliers FOR SELECT TO authenticated USING (public.can('suppliers.view'));
CREATE POLICY "suppliers_insert" ON public.suppliers FOR INSERT TO authenticated WITH CHECK (public.can('suppliers.create'));
CREATE POLICY "suppliers_update" ON public.suppliers FOR UPDATE TO authenticated
  USING (public.can('suppliers.edit')) WITH CHECK (public.can('suppliers.edit'));
CREATE POLICY "suppliers_delete" ON public.suppliers FOR DELETE TO authenticated USING (public.can('suppliers.delete'));

-- purchase orders
CREATE POLICY "po_select" ON public.purchase_orders FOR SELECT TO authenticated
  USING (public.can('purchasing.po_create') OR public.can('purchasing.po_approve') OR public.can('purchasing.request') OR public.can('finance.reports'));
CREATE POLICY "po_insert" ON public.purchase_orders FOR INSERT TO authenticated
  WITH CHECK (public.can('purchasing.po_create'));
CREATE POLICY "po_update" ON public.purchase_orders FOR UPDATE TO authenticated
  USING (public.can('purchasing.po_create') OR public.can('purchasing.po_approve') OR public.can('purchasing.receive'))
  WITH CHECK (public.can('purchasing.po_create') OR public.can('purchasing.po_approve') OR public.can('purchasing.receive'));
CREATE POLICY "po_delete" ON public.purchase_orders FOR DELETE TO authenticated USING (public.can('admin.settings'));

CREATE POLICY "po_items_select" ON public.purchase_order_items FOR SELECT TO authenticated
  USING (public.can('purchasing.po_create') OR public.can('purchasing.po_approve') OR public.can('purchasing.request') OR public.can('finance.reports'));
CREATE POLICY "po_items_manage" ON public.purchase_order_items FOR ALL TO authenticated
  USING (public.can('purchasing.po_create') OR public.can('purchasing.receive'))
  WITH CHECK (public.can('purchasing.po_create') OR public.can('purchasing.receive'));

-- finance
CREATE POLICY "invoices_select" ON public.invoices FOR SELECT TO authenticated
  USING (public.can('finance.invoices') OR public.can('finance.reports'));
CREATE POLICY "invoices_manage" ON public.invoices FOR ALL TO authenticated
  USING (public.can('finance.invoices')) WITH CHECK (public.can('finance.invoices'));

CREATE POLICY "invoice_items_select" ON public.invoice_items FOR SELECT TO authenticated
  USING (public.can('finance.invoices') OR public.can('finance.reports'));
CREATE POLICY "invoice_items_manage" ON public.invoice_items FOR ALL TO authenticated
  USING (public.can('finance.invoices')) WITH CHECK (public.can('finance.invoices'));

CREATE POLICY "payments_select" ON public.payments FOR SELECT TO authenticated
  USING (public.can('finance.payments') OR public.can('finance.reports'));
CREATE POLICY "payments_manage" ON public.payments FOR ALL TO authenticated
  USING (public.can('finance.payments')) WITH CHECK (public.can('finance.payments'));

CREATE POLICY "expenses_select" ON public.expenses FOR SELECT TO authenticated
  USING (public.can('finance.expenses') OR public.can('finance.reports') OR submitted_by = auth.uid());
CREATE POLICY "expenses_insert" ON public.expenses FOR INSERT TO authenticated
  WITH CHECK (submitted_by = auth.uid());
CREATE POLICY "expenses_update" ON public.expenses FOR UPDATE TO authenticated
  USING (public.can('finance.expenses') OR (submitted_by = auth.uid() AND status = 'pending'))
  WITH CHECK (public.can('finance.expenses') OR submitted_by = auth.uid());
CREATE POLICY "expenses_delete" ON public.expenses FOR DELETE TO authenticated USING (public.can('finance.expenses'));

-- documents
CREATE POLICY "documents_select" ON public.documents FOR SELECT TO authenticated
  USING (public.can('documents.view') AND (public.has_full_scope() OR uploaded_by = auth.uid() OR project_id IS NULL OR public.is_project_member(project_id, auth.uid())));
CREATE POLICY "documents_insert" ON public.documents FOR INSERT TO authenticated
  WITH CHECK (public.can('documents.upload') AND uploaded_by = auth.uid());
CREATE POLICY "documents_update" ON public.documents FOR UPDATE TO authenticated
  USING (public.can('documents.versions') OR public.can('documents.approve') OR uploaded_by = auth.uid())
  WITH CHECK (public.can('documents.versions') OR public.can('documents.approve') OR uploaded_by = auth.uid());
CREATE POLICY "documents_delete" ON public.documents FOR DELETE TO authenticated USING (public.can('documents.delete'));

-- settings
CREATE POLICY "company_settings_select" ON public.company_settings FOR SELECT TO authenticated USING (true);
CREATE POLICY "company_settings_update" ON public.company_settings FOR UPDATE TO authenticated
  USING (public.can('admin.settings')) WITH CHECK (public.can('admin.settings'));
CREATE POLICY "doc_counters_select" ON public.doc_counters FOR SELECT TO authenticated USING (public.can('admin.settings'));

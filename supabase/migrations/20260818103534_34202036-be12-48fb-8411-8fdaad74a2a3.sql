
-- ========== ENUMS ==========
CREATE TYPE public.app_role AS ENUM (
  'super_admin','general_manager','sales','estimation','project_manager',
  'procurement','finance','hr_admin','document_controller','employee','viewer'
);

CREATE TYPE public.data_scope AS ENUM ('all','assigned','own');

CREATE TYPE public.app_permission AS ENUM (
  'customers.view','customers.create','customers.edit','customers.delete',
  'contacts.view','contacts.create','contacts.edit','contacts.delete',
  'leads.view','leads.create','leads.edit','leads.assign','leads.close',
  'quotations.view','quotations.create','quotations.edit','quotations.submit',
  'quotations.approve','quotations.reject','quotations.send','quotations.delete',
  'projects.view','projects.create','projects.edit','projects.archive',
  'contracts.view','contracts.create','contracts.edit','contracts.delete',
  'suppliers.view','suppliers.create','suppliers.edit','suppliers.delete',
  'purchasing.rfq','purchasing.request','purchasing.po_create','purchasing.po_approve','purchasing.receive',
  'finance.invoices','finance.payments','finance.expenses','finance.vat','finance.reports',
  'documents.view','documents.upload','documents.download','documents.delete','documents.approve','documents.versions',
  'employees.view','employees.manage',
  'admin.users','admin.roles','admin.settings','admin.audit'
);

-- ========== PROFILES ==========
CREATE TABLE public.profiles (
  id UUID PRIMARY KEY REFERENCES auth.users ON DELETE CASCADE,
  full_name TEXT NOT NULL DEFAULT '',
  full_name_ar TEXT,
  email TEXT,
  phone TEXT,
  job_title TEXT,
  department TEXT,
  employee_no TEXT,
  preferred_language TEXT NOT NULL DEFAULT 'en',
  avatar_url TEXT,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.user_roles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users ON DELETE CASCADE,
  role public.app_role NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, role)
);

CREATE TABLE public.role_permissions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  role public.app_role NOT NULL,
  permission public.app_permission NOT NULL,
  UNIQUE (role, permission)
);

CREATE TABLE public.user_permissions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users ON DELETE CASCADE,
  permission public.app_permission NOT NULL,
  granted BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, permission)
);

CREATE TABLE public.user_scopes (
  user_id UUID PRIMARY KEY REFERENCES auth.users ON DELETE CASCADE,
  scope public.data_scope NOT NULL DEFAULT 'assigned',
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.audit_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id UUID,
  actor_name TEXT,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT,
  summary TEXT,
  before_data JSONB,
  after_data JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_logs_created_at ON public.audit_logs (created_at DESC);
CREATE INDEX idx_audit_logs_entity ON public.audit_logs (entity_type, entity_id);

-- ========== HELPERS ==========
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$;

CREATE TRIGGER trg_profiles_updated BEFORE UPDATE ON public.profiles
FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE OR REPLACE FUNCTION public.has_role(_user_id UUID, _role public.app_role)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT EXISTS (SELECT 1 FROM public.user_roles WHERE user_id = _user_id AND role = _role);
$$;

CREATE OR REPLACE FUNCTION public.has_permission(_user_id UUID, _perm public.app_permission)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT CASE
    WHEN EXISTS (SELECT 1 FROM public.user_roles WHERE user_id = _user_id AND role = 'super_admin') THEN true
    WHEN EXISTS (SELECT 1 FROM public.user_permissions WHERE user_id = _user_id AND permission = _perm AND granted = false) THEN false
    WHEN EXISTS (SELECT 1 FROM public.user_permissions WHERE user_id = _user_id AND permission = _perm AND granted = true) THEN true
    ELSE EXISTS (
      SELECT 1 FROM public.role_permissions rp
      JOIN public.user_roles ur ON ur.role = rp.role
      WHERE ur.user_id = _user_id AND rp.permission = _perm
    )
  END;
$$;

CREATE OR REPLACE FUNCTION public.can(_perm public.app_permission)
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT public.has_permission(auth.uid(), _perm);
$$;

CREATE OR REPLACE FUNCTION public.user_scope(_user_id UUID)
RETURNS public.data_scope LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT CASE WHEN EXISTS (SELECT 1 FROM public.user_roles WHERE user_id = _user_id AND role IN ('super_admin','general_manager'))
    THEN 'all'::public.data_scope
    ELSE COALESCE((SELECT scope FROM public.user_scopes WHERE user_id = _user_id), 'assigned'::public.data_scope) END;
$$;

-- scope check: true when user has company-wide scope
CREATE OR REPLACE FUNCTION public.has_full_scope()
RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT public.user_scope(auth.uid()) = 'all';
$$;

-- ========== NEW USER BOOTSTRAP ==========
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE is_first BOOLEAN;
BEGIN
  INSERT INTO public.profiles (id, full_name, email, avatar_url)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.raw_user_meta_data->>'name', split_part(COALESCE(NEW.email,''), '@', 1)),
    NEW.email,
    NEW.raw_user_meta_data->>'avatar_url'
  ) ON CONFLICT (id) DO NOTHING;

  SELECT COUNT(*) = 0 INTO is_first FROM public.user_roles;
  IF is_first THEN
    INSERT INTO public.user_roles (user_id, role) VALUES (NEW.id, 'super_admin') ON CONFLICT DO NOTHING;
    INSERT INTO public.user_scopes (user_id, scope) VALUES (NEW.id, 'all') ON CONFLICT DO NOTHING;
  ELSE
    INSERT INTO public.user_roles (user_id, role) VALUES (NEW.id, 'employee') ON CONFLICT DO NOTHING;
    INSERT INTO public.user_scopes (user_id, scope) VALUES (NEW.id, 'assigned') ON CONFLICT DO NOTHING;
  END IF;
  RETURN NEW;
END; $$;

CREATE TRIGGER on_auth_user_created AFTER INSERT ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ========== GRANTS ==========
GRANT SELECT, INSERT, UPDATE, DELETE ON public.profiles TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_roles TO authenticated;
GRANT SELECT ON public.role_permissions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_permissions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_scopes TO authenticated;
GRANT SELECT, INSERT ON public.audit_logs TO authenticated;
GRANT ALL ON public.profiles, public.user_roles, public.role_permissions,
  public.user_permissions, public.user_scopes, public.audit_logs TO service_role;

-- ========== RLS ==========
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.role_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_permissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_scopes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "profiles_select_all_authenticated" ON public.profiles FOR SELECT TO authenticated USING (true);
CREATE POLICY "profiles_update_self" ON public.profiles FOR UPDATE TO authenticated
  USING (id = auth.uid()) WITH CHECK (id = auth.uid());
CREATE POLICY "profiles_admin_manage" ON public.profiles FOR ALL TO authenticated
  USING (public.can('employees.manage') OR public.can('admin.users'))
  WITH CHECK (public.can('employees.manage') OR public.can('admin.users'));

CREATE POLICY "user_roles_select" ON public.user_roles FOR SELECT TO authenticated
  USING (user_id = auth.uid() OR public.can('admin.users') OR public.can('admin.roles'));
CREATE POLICY "user_roles_manage" ON public.user_roles FOR ALL TO authenticated
  USING (public.can('admin.roles')) WITH CHECK (public.can('admin.roles'));

CREATE POLICY "role_permissions_select" ON public.role_permissions FOR SELECT TO authenticated USING (true);

CREATE POLICY "user_permissions_select" ON public.user_permissions FOR SELECT TO authenticated
  USING (user_id = auth.uid() OR public.can('admin.roles') OR public.can('admin.users'));
CREATE POLICY "user_permissions_manage" ON public.user_permissions FOR ALL TO authenticated
  USING (public.can('admin.roles')) WITH CHECK (public.can('admin.roles'));

CREATE POLICY "user_scopes_select" ON public.user_scopes FOR SELECT TO authenticated
  USING (user_id = auth.uid() OR public.can('admin.users') OR public.can('admin.roles'));
CREATE POLICY "user_scopes_manage" ON public.user_scopes FOR ALL TO authenticated
  USING (public.can('admin.users')) WITH CHECK (public.can('admin.users'));

CREATE POLICY "audit_logs_select" ON public.audit_logs FOR SELECT TO authenticated
  USING (public.can('admin.audit'));
CREATE POLICY "audit_logs_insert" ON public.audit_logs FOR INSERT TO authenticated
  WITH CHECK (actor_id = auth.uid());

-- ========== DEFAULT ROLE PERMISSIONS ==========
INSERT INTO public.role_permissions (role, permission)
SELECT 'super_admin', p FROM unnest(enum_range(NULL::public.app_permission)) AS p;

INSERT INTO public.role_permissions (role, permission) VALUES
('general_manager','customers.view'),('general_manager','customers.create'),('general_manager','customers.edit'),
('general_manager','contacts.view'),('general_manager','contacts.create'),('general_manager','contacts.edit'),
('general_manager','leads.view'),('general_manager','leads.create'),('general_manager','leads.edit'),('general_manager','leads.assign'),('general_manager','leads.close'),
('general_manager','quotations.view'),('general_manager','quotations.approve'),('general_manager','quotations.reject'),('general_manager','quotations.send'),
('general_manager','projects.view'),('general_manager','projects.create'),('general_manager','projects.edit'),('general_manager','projects.archive'),
('general_manager','contracts.view'),('general_manager','contracts.create'),('general_manager','contracts.edit'),
('general_manager','suppliers.view'),('general_manager','purchasing.po_approve'),
('general_manager','finance.reports'),('general_manager','documents.view'),('general_manager','documents.download'),('general_manager','documents.approve'),
('general_manager','employees.view'),('general_manager','admin.audit'),

('sales','customers.view'),('sales','customers.create'),('sales','customers.edit'),
('sales','contacts.view'),('sales','contacts.create'),('sales','contacts.edit'),
('sales','leads.view'),('sales','leads.create'),('sales','leads.edit'),('sales','leads.close'),
('sales','quotations.view'),('sales','quotations.create'),('sales','quotations.edit'),('sales','quotations.submit'),('sales','quotations.send'),
('sales','projects.view'),('sales','contracts.view'),
('sales','documents.view'),('sales','documents.upload'),('sales','documents.download'),('sales','employees.view'),

('estimation','customers.view'),('estimation','contacts.view'),
('estimation','leads.view'),('estimation','leads.edit'),
('estimation','quotations.view'),('estimation','quotations.create'),('estimation','quotations.edit'),('estimation','quotations.submit'),
('estimation','suppliers.view'),('estimation','purchasing.rfq'),
('estimation','projects.view'),('estimation','documents.view'),('estimation','documents.upload'),('estimation','documents.download'),('estimation','employees.view'),

('project_manager','customers.view'),('project_manager','contacts.view'),
('project_manager','projects.view'),('project_manager','projects.edit'),
('project_manager','contracts.view'),('project_manager','quotations.view'),
('project_manager','suppliers.view'),('project_manager','purchasing.request'),('project_manager','purchasing.receive'),
('project_manager','documents.view'),('project_manager','documents.upload'),('project_manager','documents.download'),('project_manager','documents.approve'),
('project_manager','employees.view'),

('procurement','suppliers.view'),('procurement','suppliers.create'),('procurement','suppliers.edit'),
('procurement','purchasing.rfq'),('procurement','purchasing.request'),('procurement','purchasing.po_create'),('procurement','purchasing.receive'),
('procurement','projects.view'),('procurement','documents.view'),('procurement','documents.upload'),('procurement','documents.download'),('procurement','employees.view'),

('finance','customers.view'),('finance','projects.view'),('finance','contracts.view'),('finance','quotations.view'),
('finance','suppliers.view'),('finance','purchasing.po_approve'),
('finance','finance.invoices'),('finance','finance.payments'),('finance','finance.expenses'),('finance','finance.vat'),('finance','finance.reports'),
('finance','documents.view'),('finance','documents.upload'),('finance','documents.download'),('finance','employees.view'),

('hr_admin','employees.view'),('hr_admin','employees.manage'),
('hr_admin','documents.view'),('hr_admin','documents.upload'),('hr_admin','documents.download'),('hr_admin','admin.users'),

('document_controller','documents.view'),('document_controller','documents.upload'),('document_controller','documents.download'),
('document_controller','documents.delete'),('document_controller','documents.approve'),('document_controller','documents.versions'),
('document_controller','projects.view'),('document_controller','employees.view'),

('employee','projects.view'),('employee','documents.view'),('employee','documents.download'),('employee','employees.view'),

('viewer','customers.view'),('viewer','contacts.view'),('viewer','leads.view'),('viewer','quotations.view'),
('viewer','projects.view'),('viewer','contracts.view'),('viewer','suppliers.view'),
('viewer','finance.reports'),('viewer','documents.view'),('viewer','employees.view'),('viewer','admin.audit');

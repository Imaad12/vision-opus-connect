import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type Lang = "en" | "ar";

type Dict = Record<string, { en: string; ar: string }>;

export const dict: Dict = {
  "app.name": { en: "Vision Contracting Co.", ar: "شركة الرؤية للمقاولات" },
  "app.short": { en: "VINCO ERP", ar: "نظام فينكو" },
  "app.tagline": {
    en: "Internal ERP & CRM — sales, delivery, procurement and finance in one place.",
    ar: "نظام داخلي متكامل — المبيعات والتنفيذ والمشتريات والمالية في مكان واحد.",
  },
  "auth.signin": { en: "Sign in with Google", ar: "الدخول بحساب Google" },
  "auth.signout": { en: "Sign out", ar: "تسجيل الخروج" },
  "auth.company_only": {
    en: "Company accounts only. Access is granted by your administrator.",
    ar: "حسابات الشركة فقط. يمنح الوصول من قبل مسؤول النظام.",
  },
  "auth.signing_in": { en: "Signing in…", ar: "جارٍ الدخول…" },
  "auth.open_workspace": { en: "Open workspace", ar: "فتح النظام" },

  "nav.dashboard": { en: "Dashboard", ar: "لوحة المعلومات" },
  "nav.crm": { en: "CRM", ar: "علاقات العملاء" },
  "nav.customers": { en: "Customers", ar: "العملاء" },
  "nav.contacts": { en: "Contacts", ar: "جهات الاتصال" },
  "nav.leads": { en: "Leads", ar: "الفرص البيعية" },
  "nav.sales": { en: "Sales", ar: "المبيعات" },
  "nav.quotations": { en: "Quotations", ar: "عروض الأسعار" },
  "nav.approvals": { en: "Approvals", ar: "الاعتمادات" },
  "nav.delivery": { en: "Delivery", ar: "التنفيذ" },
  "nav.projects": { en: "Projects", ar: "المشاريع" },
  "nav.contracts": { en: "Contracts", ar: "العقود" },
  "nav.procurement": { en: "Procurement", ar: "المشتريات" },
  "nav.suppliers": { en: "Suppliers", ar: "الموردون" },
  "nav.purchase_orders": { en: "Purchase orders", ar: "أوامر الشراء" },
  "nav.finance": { en: "Finance", ar: "المالية" },
  "nav.invoices": { en: "Invoices", ar: "الفواتير" },
  "nav.payments": { en: "Payments", ar: "المدفوعات" },
  "nav.expenses": { en: "Expenses", ar: "المصروفات" },
  "nav.vat": { en: "VAT report", ar: "تقرير الضريبة" },
  "nav.documents": { en: "Documents", ar: "المستندات" },
  "nav.administration": { en: "Administration", ar: "الإدارة" },
  "nav.employees": { en: "Employees & roles", ar: "الموظفون والأدوار" },
  "nav.audit": { en: "Audit log", ar: "سجل التغييرات" },
  "nav.settings": { en: "Company settings", ar: "إعدادات الشركة" },

  "common.search": { en: "Search…", ar: "بحث…" },
  "common.new": { en: "New", ar: "جديد" },
  "common.edit": { en: "Edit", ar: "تعديل" },
  "common.delete": { en: "Delete", ar: "حذف" },
  "common.save": { en: "Save", ar: "حفظ" },
  "common.cancel": { en: "Cancel", ar: "إلغاء" },
  "common.close": { en: "Close", ar: "إغلاق" },
  "common.actions": { en: "Actions", ar: "إجراءات" },
  "common.none": { en: "None", ar: "بدون" },
  "common.start_date": { en: "Start date", ar: "تاريخ البداية" },
  "common.end_date": { en: "End date", ar: "تاريخ الانتهاء" },
  "common.empty": { en: "No records yet", ar: "لا توجد سجلات بعد" },
  "common.loading": { en: "Loading…", ar: "جارٍ التحميل…" },
  "common.load_failed": { en: "Couldn't load data", ar: "تعذر تحميل البيانات" },
  "dash.data_may_be_incomplete": {
    en: "figures below may be incomplete until this is resolved.",
    ar: "قد تكون الأرقام أدناه غير مكتملة حتى يتم حل هذه المشكلة.",
  },
  "common.no_access": {
    en: "You do not have permission to view this module.",
    ar: "لا تملك صلاحية الوصول إلى هذه الشاشة.",
  },
  "common.saved": { en: "Saved", ar: "تم الحفظ" },
  "common.deleted": { en: "Deleted", ar: "تم الحذف" },
  "common.total": { en: "Total", ar: "الإجمالي" },
  "common.status": { en: "Status", ar: "الحالة" },
  "common.details": { en: "Details", ar: "التفاصيل" },
  "common.items": { en: "Line items", ar: "البنود" },
  "common.add_item": { en: "Add line", ar: "إضافة بند" },
  "common.subtotal": { en: "Subtotal", ar: "المجموع" },
  "common.vat": { en: "VAT 15%", ar: "ضريبة القيمة المضافة ١٥٪" },
  "common.language": { en: "العربية", ar: "English" },
  "common.confirm_delete": {
    en: "Delete this record permanently?",
    ar: "حذف هذا السجل نهائياً؟",
  },
  "common.upload": { en: "Upload", ar: "رفع" },
  "common.download": { en: "Download", ar: "تنزيل" },
  "common.approve": { en: "Approve", ar: "اعتماد" },
  "common.reject": { en: "Reject", ar: "رفض" },
  "common.submit": { en: "Submit for approval", ar: "إرسال للاعتماد" },
  "common.send": { en: "Mark as sent", ar: "تم الإرسال" },
  "common.sod": {
    en: "You cannot approve a record you created or submitted.",
    ar: "لا يمكنك اعتماد سجل أنشأته أو أرسلته.",
  },
  "common.my_profile": { en: "My profile", ar: "ملفي" },

  "dash.pipeline": { en: "Open pipeline value", ar: "قيمة الفرص المفتوحة" },
  "dash.awaiting": { en: "Quotes awaiting approval", ar: "عروض بانتظار الاعتماد" },
  "dash.active_projects": { en: "Active projects", ar: "مشاريع قائمة" },
  "dash.receivables": { en: "Outstanding receivables", ar: "مستحقات غير محصلة" },
  "dash.vat_quarter": { en: "VAT collected (year)", ar: "الضريبة المحصلة (السنة)" },
  "dash.po_pending": { en: "POs awaiting approval", ar: "أوامر شراء بانتظار الاعتماد" },
  "dash.recent_activity": { en: "Recent activity", ar: "أحدث النشاطات" },
  "dash.pipeline_stage": { en: "Pipeline by stage", ar: "الفرص حسب المرحلة" },
  "items.title": { en: "Line items", ar: "بنود المستند" },
  "items.description": { en: "Description", ar: "الوصف" },
  "items.unit": { en: "Unit", ar: "الوحدة" },
  "items.qty": { en: "Qty", ar: "الكمية" },
  "items.price": { en: "Unit price", ar: "سعر الوحدة" },
  "items.line_total": { en: "Line total", ar: "إجمالي البند" },
  "items.add": { en: "Add line", ar: "إضافة بند" },
  "items.subtotal": { en: "Subtotal", ar: "المجموع قبل الضريبة" },
  "items.discount": { en: "Discount", ar: "الخصم" },
  "items.vat": { en: "VAT", ar: "ضريبة القيمة المضافة" },
  "items.total": { en: "Total", ar: "الإجمالي" },
  "doc.items": { en: "Items", ar: "البنود" },
  "doc.submitted": { en: "Submitted for approval", ar: "تم الإرسال للاعتماد" },
  "doc.approved": { en: "Approved", ar: "تم الاعتماد" },
  "doc.rejected": { en: "Rejected", ar: "تم الرفض" },
  "doc.reject_reason": { en: "Reason for rejection", ar: "سبب الرفض" },
  "doc.record_payment": { en: "Record payment", ar: "تسجيل دفعة" },
  "vat.title": { en: "VAT report", ar: "تقرير ضريبة القيمة المضافة" },
  "vat.output": { en: "Output VAT (sales)", ar: "ضريبة المخرجات (المبيعات)" },
  "vat.input": { en: "Input VAT (purchases)", ar: "ضريبة المدخلات (المشتريات)" },
  "vat.net": { en: "Net VAT payable", ar: "صافي الضريبة المستحقة" },
  "vat.period": { en: "Period", ar: "الفترة" },
  "emp.roles": { en: "Roles", ar: "الأدوار" },
  "emp.scope": { en: "Data scope", ar: "نطاق البيانات" },
  "emp.manage": { en: "Manage access", ar: "إدارة الصلاحيات" },
  "dash.welcome": { en: "Welcome back", ar: "مرحباً بعودتك" },

  "quote.new": { en: "New quotation", ar: "عرض جديد" },
  "quote.new_revision": { en: "New revision", ar: "مراجعة جديدة" },
  "quote.reference": { en: "Reference number", ar: "الرقم المرجعي" },
  "quote.title_field": { en: "Title", ar: "العنوان" },
  "quote.project": { en: "Project", ar: "المشروع" },
  "quote.client": { en: "Client", ar: "العميل" },
  "quote.version": { en: "Version", ar: "المراجعة" },
  "quote.quoted_value": { en: "Quoted value", ar: "القيمة المعروضة" },
  "quote.currency": { en: "Currency", ar: "العملة" },
  "quote.issue_date": { en: "Issue date", ar: "تاريخ الإصدار" },
  "quote.valid_until": { en: "Valid until", ar: "صالح حتى" },
  "quote.notes": { en: "Notes", ar: "ملاحظات" },
  "quote.submit": { en: "Submit", ar: "إرسال" },
  "quote.award": { en: "Award", ar: "إرساء" },
  "quote.lose": { en: "Mark lost", ar: "وضع كخاسر" },
  "quote.withdraw": { en: "Withdraw", ar: "سحب" },
  "quote.view_boq": { en: "View BOQ", ar: "عرض جدول الكميات" },
  "quote.boq_title": { en: "Bill of quantities", ar: "جدول الكميات" },
  "quote.no_boq": {
    en: "No BOQ lines yet — populated by document import, not entered manually.",
    ar: "لا توجد بنود بعد — تُستخرج عبر استيراد المستندات وليس يدوياً.",
  },
  "quote.contract_value": { en: "Contract value", ar: "قيمة العقد" },
  "quote.confirm_award": { en: "Confirm award", ar: "تأكيد الإرساء" },
  "quote.create_contract": { en: "Create contract", ar: "إنشاء عقد" },
  "contract.number": { en: "Contract number", ar: "رقم العقد" },
  "contract.signed_date": { en: "Signed date", ar: "تاريخ التوقيع" },
  "contract.activate": { en: "Activate", ar: "تفعيل" },
  "contract.complete": { en: "Mark completed", ar: "وضع كمكتمل" },
  "contract.terminate": { en: "Terminate", ar: "إنهاء" },

  "po.new": { en: "New purchase order", ar: "أمر شراء جديد" },
  "po.number": { en: "PO number", ar: "رقم أمر الشراء" },
  "po.vendor": { en: "Vendor", ar: "المورد" },
  "po.order_date": { en: "Order date", ar: "تاريخ الأمر" },
  "po.vat_rate": { en: "VAT rate %", ar: "نسبة الضريبة %" },
  "po.subtotal": { en: "Subtotal", ar: "المجموع" },
  "po.vat_amount": { en: "VAT", ar: "الضريبة" },
  "po.total": { en: "Total", ar: "الإجمالي" },
  "po.manage_lines": { en: "Manage lines", ar: "إدارة البنود" },
  "po.submit": { en: "Submit for approval", ar: "إرسال للاعتماد" },
  "po.approve": { en: "Approve", ar: "اعتماد" },
  "po.reject": { en: "Reject", ar: "رفض" },
  "po.cancel": { en: "Cancel PO", ar: "إلغاء الأمر" },
  "po.receive": { en: "Receive", ar: "استلام" },
  "po.receive_title": { en: "Record receipt", ar: "تسجيل استلام" },
  "po.remaining": { en: "Remaining", ar: "المتبقي" },
  "po.qty_to_receive": { en: "Qty received", ar: "الكمية المستلمة" },
  "po.no_lines": { en: "No lines yet", ar: "لا توجد بنود بعد" },

  "invoice.issue": { en: "Issue invoice", ar: "إصدار الفاتورة" },
  "invoice.cancel": { en: "Cancel invoice", ar: "إلغاء الفاتورة" },

  "nav.people": { en: "People", ar: "الموارد البشرية" },
  "nav.hr_employees": { en: "Employees", ar: "الموظفون" },

  "dash.operating_income": { en: "Operating income", ar: "الدخل التشغيلي" },
  "dash.net_cash_flow": { en: "Net cash flow", ar: "صافي التدفق النقدي" },
  "dash.view_management": { en: "View management report", ar: "عرض التقرير الإداري" },

  "nav.management": { en: "Management", ar: "الإدارة" },
  "mgmt.title": { en: "Management report", ar: "التقرير الإداري" },
  "mgmt.description": {
    en: "Cash flow, operating income, project profitability and vendor spend across the whole portfolio.",
    ar: "التدفق النقدي والدخل التشغيلي وربحية المشاريع وإنفاق الموردين على مستوى المحفظة.",
  },
  "mgmt.cash_in": { en: "Cash in", ar: "التدفق الداخل" },
  "mgmt.cash_out": { en: "Cash out", ar: "التدفق الخارج" },
  "mgmt.net_cash_flow": { en: "Net cash flow", ar: "صافي التدفق النقدي" },
  "mgmt.total_actual_profit": { en: "Total actual profit", ar: "إجمالي الربح الفعلي" },
  "mgmt.total_payroll_paid": { en: "Payroll paid", ar: "الرواتب المدفوعة" },
  "mgmt.operating_income": { en: "Operating income", ar: "الدخل التشغيلي" },
  "mgmt.project_profitability": { en: "Project profitability", ar: "ربحية المشاريع" },
  "mgmt.project": { en: "Project", ar: "المشروع" },
  "mgmt.client": { en: "Customer", ar: "العميل" },
  "mgmt.contract_value": { en: "Contract value", ar: "قيمة العقد" },
  "mgmt.actual_cost": { en: "Actual cost", ar: "التكلفة الفعلية" },
  "mgmt.actual_profit": { en: "Actual profit", ar: "الربح الفعلي" },
  "mgmt.margin": { en: "Margin", ar: "الهامش" },
  "mgmt.receivables": { en: "Receivables outstanding", ar: "الذمم المدينة المستحقة" },
  "mgmt.vendor_spend": { en: "Vendor spend", ar: "إنفاق الموردين" },
  "mgmt.vendor": { en: "Vendor", ar: "المورد" },
  "mgmt.po_committed": { en: "PO committed", ar: "الملتزم به بأوامر الشراء" },
  "mgmt.invoiced": { en: "Invoiced", ar: "المفوتر" },
  "mgmt.paid": { en: "Paid", ar: "المدفوع" },
  "mgmt.payable_outstanding": { en: "Payable outstanding", ar: "المستحق للموردين" },
};

type I18nValue = {
  lang: Lang;
  dir: "ltr" | "rtl";
  setLang: (l: Lang) => void;
  toggle: () => void;
  t: (key: string) => string;
};

const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");

  useEffect(() => {
    const stored = window.localStorage.getItem("vinco.lang");
    if (stored === "ar" || stored === "en") setLangState(stored);
  }, []);

  useEffect(() => {
    const dir = lang === "ar" ? "rtl" : "ltr";
    document.documentElement.setAttribute("dir", dir);
    document.documentElement.setAttribute("lang", lang);
    window.localStorage.setItem("vinco.lang", lang);
  }, [lang]);

  const setLang = useCallback((l: Lang) => setLangState(l), []);
  const toggle = useCallback(() => setLangState((p) => (p === "en" ? "ar" : "en")), []);
  const t = useCallback((key: string) => dict[key]?.[lang] ?? key, [lang]);

  const value = useMemo<I18nValue>(
    () => ({ lang, dir: lang === "ar" ? "rtl" : "ltr", setLang, toggle, t }),
    [lang, setLang, toggle, t],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used inside I18nProvider");
  return ctx;
}

export function formatMoney(value: number | null | undefined, lang: Lang = "en") {
  const n = Number(value ?? 0);
  return new Intl.NumberFormat(lang === "ar" ? "ar-SA" : "en-SA", {
    style: "currency",
    currency: "SAR",
    maximumFractionDigits: 2,
  }).format(n);
}

export function formatDate(value: string | null | undefined, lang: Lang = "en") {
  if (!value) return "—";
  const date = new Date(value);
  // Intl.DateTimeFormat.format() throws RangeError: Invalid time value for a
  // non-empty-but-unparseable string (verified directly, not assumed) --
  // e.g. a hand-typed "N/A"/"TBD" surviving in an older, loosely-typed date
  // column from before this app's date inputs enforced a real date picker.
  // A single bad row anywhere this renders (customers/documents/invoices/
  // audit logs/etc, via resource-page.tsx's generic date column, or here
  // directly) would otherwise crash the whole page it's on.
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(lang === "ar" ? "ar-SA" : "en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

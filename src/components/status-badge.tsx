import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";

const TONES: Record<string, string> = {
  neutral: "bg-muted text-muted-foreground",
  info: "bg-info/12 text-info",
  warning: "bg-warning/15 text-warning-foreground",
  success: "bg-success/14 text-success",
  danger: "bg-destructive/12 text-destructive",
  accent: "bg-accent/18 text-accent-foreground",
};

const MAP: Record<string, { tone: keyof typeof TONES; en: string; ar: string }> = {
  // generic
  active: { tone: "success", en: "Active", ar: "نشط" },
  inactive: { tone: "neutral", en: "Inactive", ar: "غير نشط" },
  draft: { tone: "neutral", en: "Draft", ar: "مسودة" },
  pending: { tone: "warning", en: "Pending", ar: "قيد الانتظار" },
  approved: { tone: "success", en: "Approved", ar: "معتمد" },
  rejected: { tone: "danger", en: "Rejected", ar: "مرفوض" },
  // leads
  new: { tone: "info", en: "New", ar: "جديد" },
  qualified: { tone: "info", en: "Qualified", ar: "مؤهل" },
  proposal: { tone: "accent", en: "Proposal", ar: "عرض مقدم" },
  negotiation: { tone: "accent", en: "Negotiation", ar: "تفاوض" },
  won: { tone: "success", en: "Won", ar: "مكسوب" },
  lost: { tone: "danger", en: "Lost", ar: "خسارة" },
  on_hold: { tone: "warning", en: "On hold", ar: "معلق" },
  // quotations
  submitted: { tone: "warning", en: "Submitted", ar: "بانتظار الاعتماد" },
  sent: { tone: "info", en: "Sent to client", ar: "أُرسل للعميل" },
  expired: { tone: "neutral", en: "Expired", ar: "منتهي" },
  revised: { tone: "accent", en: "Revised", ar: "مُعدَّل" },
  withdrawn: { tone: "neutral", en: "Withdrawn", ar: "مسحوب" },
  // projects (Supabase-shaped)
  planning: { tone: "info", en: "Planning", ar: "تخطيط" },
  completed: { tone: "success", en: "Completed", ar: "مكتمل" },
  archived: { tone: "neutral", en: "Archived", ar: "مؤرشف" },
  cancelled: { tone: "danger", en: "Cancelled", ar: "ملغي" },
  suspended: { tone: "warning", en: "Suspended", ar: "موقوف" },
  terminated: { tone: "danger", en: "Terminated", ar: "منتهي" },
  // projects (backend ProjectStatus -- values arrive uppercase; lookup
  // below lowercases first, so these keys stay lowercase like the rest)
  lead: { tone: "neutral", en: "Lead", ar: "فرصة" },
  tendering: { tone: "info", en: "Tendering", ar: "مناقصة" },
  awarded: { tone: "success", en: "Awarded", ar: "مُرسى" },
  in_progress: { tone: "accent", en: "In progress", ar: "قيد التنفيذ" },
  closed: { tone: "neutral", en: "Closed", ar: "مغلق" },
  // po
  pending_approval: { tone: "warning", en: "Pending approval", ar: "بانتظار الاعتماد" },
  partially_received: { tone: "accent", en: "Partially received", ar: "مستلم جزئياً" },
  received: { tone: "success", en: "Received", ar: "مستلم" },
  // invoices
  issued: { tone: "info", en: "Issued", ar: "صادرة" },
  partially_paid: { tone: "accent", en: "Partially paid", ar: "مدفوعة جزئياً" },
  paid: { tone: "success", en: "Paid", ar: "مدفوعة" },
  overdue: { tone: "danger", en: "Overdue", ar: "متأخرة" },
  superseded: { tone: "neutral", en: "Superseded", ar: "مستبدل" },
  // client-awarded PO (derived, client-side -- see quotations.tsx/
  // client-po.tsx; NOT a stored status column anywhere. `awarded` and
  // `lost` above are reused as-is for this same column.)
  not_awarded: { tone: "neutral", en: "Not Awarded", ar: "لم يُرسَ" },
  awaiting_client_po: { tone: "warning", en: "Awaiting Client PO", ar: "بانتظار أمر الشراء" },
  client_po_recorded: { tone: "success", en: "Client PO Recorded", ar: "تم تسجيل أمر الشراء" },
  contracted: { tone: "success", en: "Contracted", ar: "تم التعاقد" },
};

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const { lang } = useI18n();
  if (!value) return <span className="text-muted-foreground">—</span>;
  // Backend enums (e.g. ProjectStatus, QuotationStatus) arrive uppercase
  // ("LEAD", "AWARDED"); Supabase's own enums are already lowercase. One
  // case-insensitive lookup covers both without a second map.
  const entry = MAP[value.toLowerCase()];
  const tone = entry?.tone ?? "neutral";
  const label = entry ? entry[lang] : value.replace(/_/g, " ");
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONES[tone],
      )}
    >
      {label}
    </span>
  );
}

export function statusLabel(value: string, lang: "en" | "ar") {
  return MAP[value]?.[lang] ?? value.replace(/_/g, " ");
}

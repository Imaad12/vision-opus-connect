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
  // projects
  planning: { tone: "info", en: "Planning", ar: "تخطيط" },
  completed: { tone: "success", en: "Completed", ar: "مكتمل" },
  archived: { tone: "neutral", en: "Archived", ar: "مؤرشف" },
  cancelled: { tone: "danger", en: "Cancelled", ar: "ملغي" },
  suspended: { tone: "warning", en: "Suspended", ar: "موقوف" },
  terminated: { tone: "danger", en: "Terminated", ar: "منتهي" },
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
};

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const { lang } = useI18n();
  if (!value) return <span className="text-muted-foreground">—</span>;
  const entry = MAP[value];
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

import Card from "@/components/ui/Card";

const DAY_LABELS = ["M", "T", "W", "T", "F", "S", "S"];

/**
 * Home's "This week" card (redesign handoff §1). Deviation from the mock:
 * there is no per-day study-history endpoint, so the mock's sage "done"
 * fills and numeric streak ("Review today to make your streak 4 days")
 * aren't backed by anything real — inventing them would violate the
 * dashboard's "never invent numbers" rule. Only today (a fact we do know)
 * gets a highlight; every other day renders neutral, and the caption drops
 * the fabricated day count.
 */
export default function ThisWeekCard() {
  // Date.getDay(): 0=Sun..6=Sat. Shift so Monday is index 0, matching the
  // M T W T F S S label order.
  const todayIndex = (new Date().getDay() + 6) % 7;

  return (
    <Card className="flex flex-col gap-2.5">
      <span className="text-xs font-semibold uppercase tracking-[0.08em] text-sage-700">
        This week
      </span>
      <div className="flex gap-1.5">
        {DAY_LABELS.map((label, index) => {
          const isToday = index === todayIndex;
          return (
            <div key={index} className="flex-1 text-center">
              <div
                aria-hidden="true"
                className={`h-8 rounded-lg box-border ${
                  isToday ? "border-[1.5px] border-dashed border-accent" : "bg-neutral-200"
                }`}
              />
              <span className="text-[11px] text-muted-foreground">{label}</span>
            </div>
          );
        })}
      </div>
      <p className="text-[13px] text-muted-foreground">Study today to keep your streak going.</p>
    </Card>
  );
}

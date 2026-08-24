"use client";

import type {
  CurriculumConceptOut,
  CurriculumRelationOut,
  SkillEdgeOut,
  SkillNodeOut,
} from "@/lib/api/client";

import { computeSkillMapLayout, deriveLevels, SKILL_CARD_HEIGHT, SKILL_CARD_WIDTH } from "./layout";

export interface SkillMapGraphPreviewProps {
  concepts: CurriculumConceptOut[];
  relations: CurriculumRelationOut[];
}

/**
 * A compact preview of the draft curriculum's prerequisite graph — the same
 * lane/edge geometry as the published skill map, but with label-only cards
 * (no learner status/readiness, since the draft hasn't been published). Used
 * at the top of the skill-map editor so the graph stays visible while editing.
 */
export default function SkillMapGraphPreview({ concepts, relations }: SkillMapGraphPreviewProps) {
  if (concepts.length === 0) return null;

  const requires = relations.filter(
    (relation) => relation.kind === "requires" && relation.to_concept_id != null,
  );
  const levels = deriveLevels(
    concepts.map((concept) => concept.id),
    requires.map((relation) => ({
      from_id: relation.from_concept_id,
      to_id: relation.to_concept_id as string,
    })),
  );

  const nodes: SkillNodeOut[] = concepts.map((concept) => ({
    id: concept.id,
    slug: concept.stable_key,
    label: concept.label,
    level: levels[concept.id] ?? 1,
    status: "insufficient_evidence",
    section_id: concept.section_id ?? null,
    chapter_label: concept.chapter_label ?? null,
    readiness_estimate: null,
  }));
  const edges: SkillEdgeOut[] = requires.map((relation) => ({
    from_id: relation.from_concept_id,
    to_id: relation.to_concept_id as string,
    kind: "ready",
  }));

  const layout = computeSkillMapLayout(nodes, edges);

  return (
    <div className="overflow-x-auto pb-2">
      <div className="relative" style={{ width: layout.canvasWidth, height: layout.canvasHeight }}>
        <svg
          width={layout.canvasWidth}
          height={layout.canvasHeight}
          className="pointer-events-none absolute inset-0"
          aria-hidden="true"
        >
          {layout.dividers.map((d) => (
            <line
              key={`divider-${d.x}`}
              x1={d.x}
              y1={18}
              x2={d.x}
              y2={d.y2}
              stroke="var(--color-divider)"
              strokeWidth={1}
            />
          ))}
          {layout.edges.map((e) => (
            <path
              key={`edge-${e.from}-${e.to}`}
              d={e.d}
              fill="none"
              stroke="var(--sage-500)"
              strokeWidth={2.5}
            />
          ))}
          {layout.edges.map((e) => (
            <circle
              key={`dot-${e.from}-${e.to}`}
              cx={e.tx}
              cy={e.ty}
              r={4}
              fill="var(--sage-500)"
            />
          ))}
        </svg>

        {layout.lanes.map((lane) => (
          <p
            key={lane.level}
            className="absolute top-0 text-[11px] font-bold uppercase tracking-[0.1em] text-neutral-600"
            style={{ left: lane.leftPx, width: SKILL_CARD_WIDTH }}
          >
            {lane.name}
          </p>
        ))}

        {nodes.map((node) => {
          const pos = layout.nodePositions[node.id];
          if (!pos) return null;
          return (
            <div
              key={node.id}
              style={{ left: pos.leftPx, top: pos.topPx, width: SKILL_CARD_WIDTH, height: SKILL_CARD_HEIGHT }}
              className="absolute flex flex-col justify-center gap-[7px] rounded-lg border border-divider bg-surface-raised p-[14px_16px] text-foreground shadow-sm"
            >
              <span className="text-sm font-bold">{node.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

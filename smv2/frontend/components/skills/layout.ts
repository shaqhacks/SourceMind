import type { SkillEdgeOut, SkillNodeOut } from "@/lib/api/client";

/**
 * Skill map geometry — ported from the design handoff's prototype
 * (`Redesign - Skill Map.dc.html`, inline `<script>`). Lanes are built from
 * each node's `level` (1 lane per distinct level, ascending); within a lane,
 * nodes keep `SKILL_NODES`' array order, so row assignment is stable across
 * renders. Constants (card size, pitches) are copied verbatim from the mock
 * so the layout matches pixel-for-pixel.
 */

const CARD_W = 260;
const CARD_H = 118;
const LANE_PITCH = 370;
const ROW_PITCH = 170;
const TOP = 30;
/** Distance (px) each additional incoming edge fans out from center — the
 * mock's own constant; with exactly 2 siblings this yields the ±7px the
 * design calls for. */
const FAN_SPREAD = 14;
const CURVE_CONTROL_OFFSET = 55;

export interface LaneLayout {
  level: number;
  name: string;
  leftPx: number;
}

export interface NodePosition {
  leftPx: number;
  topPx: number;
}

export interface EdgeLayout {
  from: string;
  to: string;
  kind: SkillEdgeOut["kind"];
  /** SVG path `d` attribute — straight line when source/target share a row,
   * cubic Bézier otherwise. */
  d: string;
  /** Target-end coordinates, for the 4px dot marker. */
  tx: number;
  ty: number;
}

export interface DividerLayout {
  x: number;
  y2: number;
}

export interface SkillMapLayout {
  lanes: LaneLayout[];
  nodePositions: Record<string, NodePosition>;
  edges: EdgeLayout[];
  dividers: DividerLayout[];
  canvasWidth: number;
  canvasHeight: number;
}

export function computeSkillMapLayout(nodes: SkillNodeOut[], edges: SkillEdgeOut[]): SkillMapLayout {
  const levels = Array.from(new Set(nodes.map((n) => n.level))).sort((a, b) => a - b);

  const lanes: LaneLayout[] = levels.map((level, laneIndex) => ({
    level,
    name: level === 1 ? "Level 1 · Foundations" : `Level ${level}`,
    leftPx: laneIndex * LANE_PITCH,
  }));

  const nodePositions: Record<string, NodePosition> = {};
  let maxRows = 0;
  levels.forEach((level, laneIndex) => {
    const rowNodes = nodes.filter((n) => n.level === level);
    maxRows = Math.max(maxRows, rowNodes.length);
    rowNodes.forEach((node, rowIndex) => {
      nodePositions[node.id] = {
        leftPx: laneIndex * LANE_PITCH,
        topPx: TOP + rowIndex * ROW_PITCH,
      };
    });
  });

  // Spread multiple edges landing on one node so their dots/curves don't
  // overlap — mirrors the mock's `incoming` map + index-based offset.
  const incoming = new Map<string, SkillEdgeOut[]>();
  edges.forEach((e) => {
    const list = incoming.get(e.to_id) ?? [];
    list.push(e);
    incoming.set(e.to_id, list);
  });

  const edgeLayouts: EdgeLayout[] = [];
  edges.forEach((e) => {
    const a = nodePositions[e.from_id];
    const b = nodePositions[e.to_id];
    if (!a || !b) return; // defensive: an edge referencing an unknown node id

    const sibs = incoming.get(e.to_id) ?? [];
    const idx = sibs.indexOf(e);
    const spread = sibs.length > 1 ? (idx - (sibs.length - 1) / 2) * FAN_SPREAD : 0;

    const x1 = a.leftPx + CARD_W;
    const y1 = a.topPx + CARD_H / 2;
    const x2 = b.leftPx;
    const y2 = b.topPx + CARD_H / 2 + spread;

    const d =
      Math.abs(y1 - y2) < 1
        ? `M ${x1} ${y1} L ${x2} ${y2}`
        : `M ${x1} ${y1} C ${x1 + CURVE_CONTROL_OFFSET} ${y1}, ${x2 - CURVE_CONTROL_OFFSET} ${y2}, ${x2} ${y2}`;

    edgeLayouts.push({ from: e.from_id, to: e.to_id, kind: e.kind, d, tx: x2, ty: y2 });
  });

  const canvasWidth = levels.length * LANE_PITCH - (LANE_PITCH - CARD_W);
  const canvasHeight = TOP + maxRows * ROW_PITCH - (ROW_PITCH - CARD_H);

  const dividers: DividerLayout[] = [];
  for (let i = 1; i < levels.length; i++) {
    dividers.push({ x: i * LANE_PITCH - (LANE_PITCH - CARD_W) / 2, y2: canvasHeight });
  }

  return { lanes, nodePositions, edges: edgeLayouts, dividers, canvasWidth, canvasHeight };
}

export const SKILL_CARD_WIDTH = CARD_W;
export const SKILL_CARD_HEIGHT = CARD_H;

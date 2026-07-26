/**
 * SAMPLE DATA — competency/skill-map placeholder.
 *
 * The prereq-graph backend (PrereqConcept/PrereqEdge/PrereqLink, approved
 * 2026-07-26 office hours) does not exist yet. Until it does, the Skill
 * Map, Competency detail, and Home "Skill snapshot" render from this
 * module and must visibly tag themselves as sample data (the mocks'
 * "sample data" tag). Shapes mirror the planned API contract so the swap
 * to `lib/api/client.ts` helpers is mechanical: when the endpoints land,
 * replace imports of this module, delete it, and drop the tags.
 *
 * No component outside these three surfaces may import this module.
 */

export type SkillStatus = "solid" | "growing" | "struggling" | "locked";

export interface SkillNode {
  id: string;
  name: string;
  /** 1-based lane: Level 1 = Foundations. */
  level: number;
  status: SkillStatus;
  /** 0-100 derived mastery score. */
  mastery: number;
  /** One-line note shown on the skill card. */
  note: string;
  /** Prerequisite skill ids (edge sources pointing at this node). */
  prereqIds: string[];
  /** Where this skill is taught: chapter/section refs for the detail page. */
  taughtIn: { chapterLabel: string; sectionTitle: string; relevance: string }[];
  /** "Unlocks at N mastery of X" note for locked nodes. */
  unlockNote?: string;
}

export interface SkillEdge {
  from: string;
  to: string;
  /** met = solid sage line; weak = dashed terracotta (fix this first). */
  kind: "met" | "weak";
}

export interface MissedQuestion {
  question: string;
  yourAnswer: string;
  correctAnswer: string;
  source: string;
}

export const SAMPLE_DATA_LABEL = "Sample data";

export const SKILL_NODES: SkillNode[] = [
  {
    id: "tokenization",
    name: "Tokenization basics",
    level: 1,
    status: "solid",
    mastery: 86,
    note: "Strong across cards and the chapter 1 test.",
    prereqIds: [],
    taughtIn: [
      {
        chapterLabel: "Chapter 1",
        sectionTitle: "How text becomes tokens",
        relevance: "Defines tokens, vocabularies, and byte-pair encoding.",
      },
    ],
  },
  {
    id: "token-counting",
    name: "Token counting",
    level: 1,
    status: "struggling",
    mastery: 31,
    note: "Missed on the last two quizzes.",
    prereqIds: ["tokenization"],
    taughtIn: [
      {
        chapterLabel: "Chapter 2",
        sectionTitle: "Counting and budgeting tokens",
        relevance: "Counting rules, context windows, and budget math.",
      },
      {
        chapterLabel: "Chapter 1",
        sectionTitle: "How text becomes tokens",
        relevance: "Where token boundaries come from.",
      },
    ],
  },
  {
    id: "prompt-structure",
    name: "Prompt structure",
    level: 1,
    status: "growing",
    mastery: 58,
    note: "Solid on roles, shaky on ordering effects.",
    prereqIds: [],
    taughtIn: [
      {
        chapterLabel: "Chapter 2",
        sectionTitle: "Anatomy of a prompt",
        relevance: "System/user roles and instruction placement.",
      },
    ],
  },
  {
    id: "cost-estimation",
    name: "Cost estimation",
    level: 2,
    status: "struggling",
    mastery: 24,
    note: "Blocked by weak token counting.",
    prereqIds: ["token-counting"],
    taughtIn: [
      {
        chapterLabel: "Chapter 3",
        sectionTitle: "Pricing and budgets",
        relevance: "Per-token pricing math over real workloads.",
      },
    ],
  },
  {
    id: "context-management",
    name: "Context management",
    level: 2,
    status: "growing",
    mastery: 52,
    note: "Understands windows; truncation strategies are new.",
    prereqIds: ["token-counting", "prompt-structure"],
    taughtIn: [
      {
        chapterLabel: "Chapter 3",
        sectionTitle: "Fitting work into the window",
        relevance: "Truncation, summarization, and packing strategies.",
      },
    ],
  },
  {
    id: "caching",
    name: "Prompt caching",
    level: 3,
    status: "locked",
    mastery: 0,
    note: "Not started yet.",
    prereqIds: ["cost-estimation", "context-management"],
    unlockNote: "Unlocks at 60 mastery of Cost estimation",
    taughtIn: [
      {
        chapterLabel: "Chapter 4",
        sectionTitle: "Caching and reuse",
        relevance: "Cache breakpoints and hit-rate economics.",
      },
    ],
  },
];

export const SKILL_EDGES: SkillEdge[] = SKILL_NODES.flatMap((node) =>
  node.prereqIds.map((from) => {
    const prereq = SKILL_NODES.find((n) => n.id === from);
    const weak = prereq !== undefined && prereq.mastery < 60;
    return { from, to: node.id, kind: weak ? "weak" : "met" } as SkillEdge;
  }),
);

export const MISSED_QUESTIONS: Record<string, MissedQuestion[]> = {
  "token-counting": [
    {
      question: "A 3,000-word document is roughly how many tokens?",
      yourAnswer: "~1,500 tokens",
      correctAnswer: "~4,000 tokens",
      source: "Chapter 2 test · attempt 2 · 3 days ago",
    },
    {
      question: "Which change reduces token count the most?",
      yourAnswer: "Shorter variable names",
      correctAnswer: "Removing repeated boilerplate",
      source: "Chapter 2 test · attempt 2 · 3 days ago",
    },
  ],
  "cost-estimation": [
    {
      question: "Estimate the monthly cost of 10k calls at 2k input tokens each.",
      yourAnswer: "Off by 10×",
      correctAnswer: "Multiply calls × tokens × per-token rate",
      source: "Chapter 3 test · attempt 1 · yesterday",
    },
  ],
};

export function getSkill(id: string): SkillNode | undefined {
  return SKILL_NODES.find((n) => n.id === id);
}

/** Skills directly blocked by `id` (it appears in their prereqs). */
export function blockedBy(id: string): SkillNode[] {
  return SKILL_NODES.filter((n) => n.prereqIds.includes(id));
}

/** The weakest struggling skill whose prereq chain explains it — drives the
 * "Why you're stuck" callout on Home and the map's "Recommended fix". */
export function rootCause(): { skill: SkillNode; prereq: SkillNode } | null {
  for (const node of SKILL_NODES) {
    if (node.status !== "struggling") continue;
    const weakPrereq = node.prereqIds
      .map((id) => getSkill(id))
      .find((p): p is SkillNode => p !== undefined && p.mastery < 60);
    if (weakPrereq) return { skill: node, prereq: weakPrereq };
  }
  return null;
}

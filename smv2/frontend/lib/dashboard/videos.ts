/**
 * Curated, deterministic list of learning-science explainers shown at the
 * bottom of the dashboard (spec §4). Every videoId below was verified live
 * against the YouTube oEmbed endpoint at authoring time (Task 5 Step 1) —
 * `https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=<id>&format=json`
 * — and the `title` field here is copied verbatim from that response, so
 * this file is never a guess from memory. See task-5-report.md for the
 * full id -> returned-title evidence table.
 */
export interface LearningVideo {
  videoId: string;
  title: string;
  blurb: string;
}

export const LEARNING_VIDEOS: LearningVideo[] = [
  {
    videoId: "rhgwIhB58PA",
    title: "The Biggest Myth In Education",
    blurb:
      "Veritasium walks through a randomized controlled trial showing no benefit to teaching students in their supposedly preferred learning style.",
  },
  {
    videoId: "Z-zNHHpXoMM",
    title: "How to Study for Exams - Spaced Repetition | Evidence-based revision tips",
    blurb:
      "Explains the spacing effect: reviewing material at increasing intervals produces far better long-term retention than cramming it in one sitting.",
  },
  {
    videoId: "fDbxPVn02VU",
    title: "How my friend ranked 1st at Medical School - The Active Recall Framework",
    blurb:
      "Breaks down active recall — testing yourself on material instead of re-reading it — as the technique credited with topping a medical school class.",
  },
  {
    videoId: "mzexJPoXBCM",
    title: "How to Study & Learn Using Active Recall | Dr. Cal Newport & Dr. Andrew Huberman",
    blurb:
      "Neuroscientist Andrew Huberman and computer scientist Cal Newport discuss why retrieving information from memory drives durable learning better than passive review.",
  },
  {
    videoId: "vd2dtkMINIw",
    title: "Barbara Oakley | Learning How to Learn | Talks at Google",
    blurb:
      "Barbara Oakley, co-creator of Coursera's most-enrolled course, explains spaced repetition and chunking as tools for mastering difficult subjects.",
  },
];

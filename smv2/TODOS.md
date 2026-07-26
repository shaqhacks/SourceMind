# TODOS

## Course-level tab navigation (Reader · Cards · Quizzes · Map)
- **What:** shared course header nav making the four surfaces one click apart.
- **Why:** the mastery map ships as a bare route link; the approved wireframe's tab strip tested well visually, but no shared nav component exists in the frontend today.
- **Pros:** map discoverability; one navigation idiom as surfaces multiply (review, quizzes, map, phase-B tutor).
- **Cons:** touches every course page's layout; pure chrome with zero learning value on its own.
- **Context (2026-07-26, /plan-eng-review):** cards/quizzes are currently reached via inline CTAs in the reading column and separate routes. Start by extracting the map route's header upward. Wireframe reference: `~/.gstack/projects/smv2/designs/mockup-20260726/mastery-map-wireframe-v4.png`.
- **Depends on / blocked by:** the map route existing (prereq-graph slice, task T8).

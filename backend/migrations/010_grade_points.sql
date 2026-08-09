-- Grade points on the banding scale, so a GPA has a number to average.
--
-- Not an ALTER TABLE: the scale is a JSON document in `organization.grading_scale_json`,
-- so the shape change lives in `GradingScale.from_list`, which treats a missing `points`
-- as unset rather than an error. Every scale stored before today keeps loading.
--
-- This statement only prices the shipped A/B/C/D/F default, and only where it is still
-- exactly as seeded. The equality test on the whole document is the safety: an
-- institution that has edited its scale -- reordered it, renamed a band, moved a
-- threshold -- does not match, is left alone, and sets its own points. There is no
-- correct guess to make on its behalf. A German 1-6 scale awards its lowest number to
-- its highest threshold, and inferring points from position would silently invert it.
-- One long literal on purpose: SQL has no adjacent-string-literal concatenation, so
-- splitting this across lines the way Python would is a syntax error rather than a
-- formatting choice. `001_core.sql` writes the same document the same way.
UPDATE organization
   SET grading_scale_json =
       '[{"min_percentage":90,"label":"A","points":4.0},{"min_percentage":80,"label":"B","points":3.0},{"min_percentage":70,"label":"C","points":2.0},{"min_percentage":60,"label":"D","points":1.0},{"min_percentage":0,"label":"F","points":0.0}]'
 WHERE id = 1
   AND grading_scale_json IN (
       -- As `001_core.sql` seeds it: compact, integer thresholds.
       '[{"min_percentage":90,"label":"A"},{"min_percentage":80,"label":"B"},{"min_percentage":70,"label":"C"},{"min_percentage":60,"label":"D"},{"min_percentage":0,"label":"F"}]',
       -- And as it comes back out of `json.dumps` after any branding save has
       -- rewritten the row: spaced separators, floats. Same document, different
       -- spelling -- and an installation that merely saved its colours has not
       -- customised its grading scale.
       '[{"min_percentage": 90.0, "label": "A"}, {"min_percentage": 80.0, "label": "B"}, {"min_percentage": 70.0, "label": "C"}, {"min_percentage": 60.0, "label": "D"}, {"min_percentage": 0.0, "label": "F"}]'
   );

INSERT INTO places (id, name, category, city, neighborhood, latitude, longitude)
VALUES
  ('11111111-1111-1111-1111-111111111111', 'Han Bun Bakery', 'bakery', 'Fort Lee', 'Main Street', 40.8509, -73.9701),
  ('22222222-2222-2222-2222-222222222222', 'River Desk Cafe', 'cafe', 'Edgewater', 'River Road', 40.8270, -73.9757),
  ('33333333-3333-3333-3333-333333333333', 'Seoul Table', 'restaurant', 'Palisades Park', 'Broad Avenue', 40.8482, -73.9976)
ON CONFLICT (id) DO NOTHING;

INSERT INTO signals (id, place_id, signal_type, title, summary, evidence, score, city, week_start)
VALUES
  (
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    '11111111-1111-1111-1111-111111111111',
    'keyword_spike',
    'Han Bun Bakery is suddenly rising',
    'Han Bun Bakery appears to be moving from a neighborhood bakery into a regional food stop, with salt bread driving the attention.',
    '{"review_velocity": 4.8, "keywords": ["salt bread", "line", "Manhattan"], "sources": ["google_reviews", "reddit"]}',
    91.5,
    'Fort Lee',
    date_trunc('week', now())::date
  ),
  (
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    '22222222-2222-2222-2222-222222222222',
    'behavior_shift',
    'River Desk Cafe is becoming a remote-work hotspot',
    'Weekday afternoon mentions increasingly describe quiet seating, outlets, and longer stays.',
    '{"review_velocity": 2.7, "keywords": ["wifi", "outlet", "quiet"], "sources": ["google_reviews", "yelp"]}',
    78.2,
    'Edgewater',
    date_trunc('week', now())::date
  ),
  (
    'cccccccc-cccc-cccc-cccc-cccccccccccc',
    '33333333-3333-3333-3333-333333333333',
    'sentiment_shift',
    'Seoul Table has early signs of quality drift',
    'Recent mentions remain busy but show a mild increase in service and wait-time complaints.',
    '{"sentiment_delta": -0.18, "keywords": ["wait", "service", "crowded"], "sources": ["google_reviews"]}',
    69.4,
    'Palisades Park',
    date_trunc('week', now())::date
  )
ON CONFLICT (id) DO NOTHING;

INSERT INTO reports (id, title, region, week_start, intro)
VALUES (
  'dddddddd-dddd-dddd-dddd-dddddddddddd',
  'This Week Nearby',
  'Fort Lee / Edgewater / Palisades Park',
  date_trunc('week', now())::date,
  'A quick read on the local places showing unusual momentum, behavior changes, or early quality shifts.'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO report_signals (report_id, signal_id, rank)
VALUES
  ('dddddddd-dddd-dddd-dddd-dddddddddddd', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 1),
  ('dddddddd-dddd-dddd-dddd-dddddddddddd', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 2),
  ('dddddddd-dddd-dddd-dddd-dddddddddddd', 'cccccccc-cccc-cccc-cccc-cccccccccccc', 3)
ON CONFLICT (report_id, signal_id) DO NOTHING;

INSERT INTO places (id, name, category, city, neighborhood, latitude, longitude)
VALUES
  ('11111111-1111-1111-1111-111111111111', 'Han Bun Bakery', 'bakery', 'Fort Lee', 'Main Street', 40.8509, -73.9701),
  ('22222222-2222-2222-2222-222222222222', 'River Desk Cafe', 'cafe', 'Edgewater', 'River Road', 40.8270, -73.9757),
  ('33333333-3333-3333-3333-333333333333', 'Seoul Table', 'restaurant', 'Palisades Park', 'Broad Avenue', 40.8482, -73.9976)
ON CONFLICT (id) DO NOTHING;

INSERT INTO places (id, name, category, city, neighborhood, latitude, longitude)
VALUES
  ('11111111-1111-1111-1111-111111111111', 'BCD Tofu House', 'restaurant', 'Fort Lee', 'Schlosser Street', 40.8582, -73.9698),
  ('22222222-2222-2222-2222-222222222222', 'Kuppi Coffee Company', 'cafe', 'Edgewater', 'River Road', 40.8214, -73.9788),
  ('33333333-3333-3333-3333-333333333333', 'So Gong Dong Tofu & BBQ', 'restaurant', 'Palisades Park', 'Broad Avenue', 40.8476, -73.9971)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  category = EXCLUDED.category,
  city = EXCLUDED.city,
  neighborhood = EXCLUDED.neighborhood,
  latitude = EXCLUDED.latitude,
  longitude = EXCLUDED.longitude;

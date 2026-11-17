CREATE TABLE catalog_units (
    code TEXT PRIMARY KEY NOT NULL,
    base TEXT NOT NULL,
    ticks INTEGER NOT NULL,
    CHECK ((code='g' AND base='g' AND ticks=1000)
        OR (code='kg' AND base='g' AND ticks=1000000)
        OR (code='ml' AND base='ml' AND ticks=1000)
        OR (code='l' AND base='ml' AND ticks=1000000)
        OR (code='quả' AND base='quả' AND ticks=1))
);
INSERT INTO catalog_units VALUES ('g','g',1000),('kg','g',1000000),('ml','ml',1000),('l','ml',1000000),('quả','quả',1);
CREATE TABLE food_products (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL, category TEXT NOT NULL,
    base_unit TEXT NOT NULL REFERENCES catalog_units(code) CHECK (base_unit IN ('g','ml','quả')),
    UNIQUE(name_key,category,base_unit), UNIQUE(id,base_unit)
);
CREATE TABLE food_aliases (
    product_id INTEGER NOT NULL REFERENCES food_products, alias_key TEXT NOT NULL, source TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK(review_status IN ('pending','approved','rejected')),
    PRIMARY KEY(product_id,alias_key)
);
INSERT INTO food_products VALUES (1,'Gạo','gạo','Ngũ cốc','g'),(2,'Trứng gà','trứng gà','Trứng','quả'),(3,'Sữa bò','sữa bò','Sữa','ml'),(4,'Cà rốt','cà rốt','Rau củ','g');
INSERT INTO food_aliases VALUES (2,'trứng','local-demo','approved'),(3,'sữa tươi','local-demo','approved');

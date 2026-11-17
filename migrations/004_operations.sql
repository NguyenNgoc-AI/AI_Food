CREATE TABLE operation_keys (
    household_id INTEGER NOT NULL REFERENCES households, key TEXT NOT NULL, signature TEXT NOT NULL,
    result TEXT NOT NULL, PRIMARY KEY(household_id,key)
);
CREATE TABLE batches (
    id INTEGER PRIMARY KEY, household_id INTEGER NOT NULL REFERENCES households, product_id INTEGER NOT NULL,
    base_unit TEXT NOT NULL, received TEXT NOT NULL, expiry TEXT, expiry_source TEXT NOT NULL, flagged INTEGER NOT NULL DEFAULT 0,
    ticks INTEGER NOT NULL CHECK(typeof(ticks)='integer' AND ticks>=0), version INTEGER NOT NULL DEFAULT 1, original TEXT NOT NULL,
    FOREIGN KEY(product_id,base_unit) REFERENCES food_products(id,base_unit)
);
CREATE INDEX batch_fifo ON batches(household_id,product_id,received,id);
CREATE TABLE movements (
    id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES batches, actor INTEGER NOT NULL REFERENCES users,
    kind TEXT NOT NULL CHECK(kind IN ('receive','consume','waste','adjust')), delta INTEGER NOT NULL, reason TEXT NOT NULL,
    occurred TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX movement_batch ON movements(batch_id,id);
CREATE TABLE receipts (
    id INTEGER PRIMARY KEY, household_id INTEGER NOT NULL REFERENCES households, actor INTEGER NOT NULL REFERENCES users,
    fingerprint TEXT NOT NULL, draft TEXT NOT NULL, confirmed TEXT
);
CREATE INDEX receipt_duplicates ON receipts(household_id,fingerprint);
CREATE TABLE alert_reads (
    batch_id INTEGER NOT NULL REFERENCES batches, user_id INTEGER NOT NULL REFERENCES users, state TEXT NOT NULL,
    PRIMARY KEY(batch_id,user_id,state)
);
CREATE TABLE dietary_profiles (
    user_id INTEGER PRIMARY KEY REFERENCES users, settings TEXT NOT NULL
);
CREATE TABLE recipes (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, allergens TEXT NOT NULL, tags TEXT NOT NULL, complete INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'local-demo'
);
CREATE TABLE ingredients (
    recipe_id INTEGER NOT NULL REFERENCES recipes, product_id INTEGER NOT NULL REFERENCES food_products,
    ticks_per_serving INTEGER NOT NULL CHECK(typeof(ticks_per_serving)='integer' AND ticks_per_serving>0), PRIMARY KEY(recipe_id,product_id)
);
INSERT INTO recipes(id,name,allergens,tags,complete) VALUES (1,'Cháo gạo cà rốt','[]','["chay"]',1),(2,'Cơm trứng','["trứng"]','[]',1);
INSERT INTO ingredients VALUES (1,1,50000),(1,4,30000),(2,1,80000),(2,2,1);
CREATE TABLE meal_plans (
    id INTEGER PRIMARY KEY, household_id INTEGER NOT NULL REFERENCES households, recipe_id INTEGER NOT NULL REFERENCES recipes,
    day TEXT NOT NULL, meal TEXT NOT NULL, servings INTEGER NOT NULL CHECK(servings>0), participants TEXT NOT NULL
);


CREATE TABLE grocery_lists (
    id INTEGER PRIMARY KEY, household_id INTEGER NOT NULL REFERENCES households, start TEXT NOT NULL, end TEXT NOT NULL
);
CREATE TABLE grocery_items (
    list_id INTEGER NOT NULL REFERENCES grocery_lists, product_id INTEGER NOT NULL REFERENCES food_products,
    ticks TEXT NOT NULL, purchased INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(list_id,product_id)
);

CREATE TRIGGER recipe_unit_immutable BEFORE UPDATE OF base_unit ON food_products
WHEN OLD.base_unit != NEW.base_unit AND EXISTS (SELECT 1 FROM ingredients WHERE product_id=OLD.id)
BEGIN
    SELECT RAISE(ABORT,'Referenced recipe unit');
END;

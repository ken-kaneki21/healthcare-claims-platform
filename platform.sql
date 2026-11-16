PRAGMA foreign_keys = ON;

CREATE TABLE client(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, cost_factor INTEGER NOT NULL);
INSERT INTO client VALUES (1,'Fictional North',100),(2,'Fictional South',118);
INSERT INTO client SELECT 3,'Fictional West',91 FROM config WHERE tenants=3;
CREATE TABLE provider(
    client_id INTEGER REFERENCES client(id), id INTEGER, region TEXT NOT NULL,
    PRIMARY KEY(client_id,id)
) WITHOUT ROWID;
INSERT INTO provider SELECT c.id,n.id,printf('%05d',1000+n.id%20)
FROM client c CROSS JOIN numbers n WHERE n.id<=250;

CREATE TABLE member(
    client_id INTEGER REFERENCES client(id), id INTEGER, age_band INTEGER NOT NULL,
    cohort TEXT NOT NULL, assigned_provider INTEGER NOT NULL, propensity INTEGER NOT NULL,
    PRIMARY KEY(client_id,id), FOREIGN KEY(client_id,assigned_provider) REFERENCES provider(client_id,id)
) WITHOUT ROWID;
INSERT INTO member
SELECT 1+(id%tenants),id,(id*13+seed)%5,
       CASE WHEN (id*37+seed)%11=0 THEN 'high_needs' ELSE 'standard' END,
       1+(id*73+seed)%250, 1+(id*437+seed*31)%15
FROM numbers CROSS JOIN config WHERE id<=members;

CREATE TABLE month(id INTEGER PRIMARY KEY, starts TEXT UNIQUE NOT NULL);
INSERT INTO month
SELECT id,date('2024-01-01',printf('+%d months',id-1))
FROM numbers CROSS JOIN config WHERE id<=months;
CREATE TABLE member_month(
    client_id INTEGER, member_id INTEGER, month_id INTEGER REFERENCES month(id),
    provider_id INTEGER NOT NULL,
    PRIMARY KEY(client_id,member_id,month_id),
    FOREIGN KEY(client_id,member_id) REFERENCES member(client_id,id),
    FOREIGN KEY(client_id,provider_id) REFERENCES provider(client_id,id)
) WITHOUT ROWID;
INSERT INTO member_month
SELECT m.client_id,m.id,d.id,
  CASE WHEN d.id>=13 AND m.id%9=0 THEN 1+m.assigned_provider%250 ELSE m.assigned_provider END
FROM member m CROSS JOIN month d
WHERE d.id>CASE WHEN m.id%7=0 THEN m.id%4 ELSE 0 END
  AND d.id<=(SELECT months FROM config)-CASE WHEN m.id%13=0 THEN m.id%5 ELSE 0 END;

CREATE TABLE member_alias(
    client_id INTEGER, member_id INTEGER, alias TEXT, valid_from INTEGER, valid_until INTEGER,
    PRIMARY KEY(client_id,alias), FOREIGN KEY(client_id,member_id) REFERENCES member(client_id,id)
) WITHOUT ROWID;
INSERT INTO member_alias
SELECT client_id,id,printf('SYN-%07d-A',id),1,CASE WHEN id%23=0 THEN 13 ELSE 25 END FROM member
UNION ALL SELECT client_id,id,printf('SYN-%07d-B',id),13,25 FROM member WHERE id%23=0;

CREATE TABLE rate(
    client_id INTEGER REFERENCES client(id), region TEXT, year INTEGER, cohort TEXT,
    cents INTEGER NOT NULL, PRIMARY KEY(client_id,region,year,cohort)
) WITHOUT ROWID;
INSERT INTO rate
SELECT p.client_id,p.region,y.id+2023,cohort.name,
       (55000+CAST(p.region AS INTEGER)*11+y.id*2300+cohort.premium)*c.cost_factor/100
FROM (SELECT DISTINCT client_id,region FROM provider) p
JOIN client c ON c.id=p.client_id
CROSS JOIN (SELECT id FROM numbers WHERE id<=2) y
CROSS JOIN (SELECT 'standard' AS name,0 AS premium UNION ALL SELECT 'high_needs',17000) cohort;

CREATE TABLE risk_snapshot(
    client_id INTEGER,member_id INTEGER,month_id INTEGER REFERENCES month(id),risk_basis_points INTEGER,
    PRIMARY KEY(client_id,member_id,month_id), FOREIGN KEY(client_id,member_id) REFERENCES member(client_id,id)
) WITHOUT ROWID;
INSERT INTO risk_snapshot
SELECT m.client_id,m.id,d.id,
       CASE WHEN (m.id+d.id)%149<>0 THEN 6700+m.age_band*500+m.propensity*321+(m.id*d.id)%1900 END
FROM member m CROSS JOIN month d WHERE (d.id-1)%3=0;

CREATE TABLE claim(
    id INTEGER PRIMARY KEY,client_id INTEGER,member_id INTEGER,month_id INTEGER,
    provider_id INTEGER, service_date TEXT NOT NULL,kind INTEGER NOT NULL CHECK(kind BETWEEN 0 AND 2),
    FOREIGN KEY(client_id,member_id,month_id) REFERENCES member_month(client_id,member_id,month_id),
    FOREIGN KEY(client_id,provider_id) REFERENCES provider(client_id,id)
);
INSERT INTO claim
SELECT (e.member_id-1)*48+(e.month_id-1)*2+s.id,e.client_id,e.member_id,e.month_id,
       CASE WHEN (e.member_id+e.month_id+s.id)%113<>0 THEN e.provider_id END,
       date(d.starts,printf('+%d days',abs((e.member_id*47+e.month_id*103+s.id*131+seed)%27911)%28)),
       (e.member_id*13+e.month_id*7+s.id*5+seed)%10/4
FROM member_month e JOIN month d ON d.id=e.month_id
JOIN member m ON m.client_id=e.client_id AND m.id=e.member_id
CROSS JOIN config CROSS JOIN (SELECT id FROM numbers WHERE id<=2) s
WHERE (e.member_id*311+e.month_id*791+s.id*277+e.member_id*e.month_id*13+seed)%100
          < 57 + m.propensity*2 + (e.month_id%12 IN (1,2,0))*3;
CREATE TABLE encounter(id INTEGER PRIMARY KEY REFERENCES claim(id), setting TEXT NOT NULL);
INSERT INTO encounter SELECT id,CASE kind WHEN 0 THEN 'facility' WHEN 1 THEN 'office' ELSE 'pharmacy' END
FROM claim;
CREATE TABLE diagnosis(
    claim_id INTEGER REFERENCES claim(id), sequence INTEGER, condition_group TEXT NOT NULL,
    PRIMARY KEY(claim_id,sequence)
) WITHOUT ROWID;
INSERT INTO diagnosis
SELECT c.id,n.id,printf('SYN-COND-%02d',(c.id*19+c.member_id*3+n.id*13)%23)
FROM claim c CROSS JOIN (SELECT id FROM numbers WHERE id<=2) n
WHERE c.kind<>2 AND (n.id=1 OR c.id%5=0);

CREATE TABLE payment_event(
    claim_id INTEGER REFERENCES claim(id), line_no INTEGER, version INTEGER,
    paid_date TEXT NOT NULL, received_date TEXT NOT NULL, delta_cents INTEGER NOT NULL,
    PRIMARY KEY(claim_id,line_no,version)
) WITHOUT ROWID;
INSERT INTO payment_event
SELECT c.id,n.id,1,
       date(c.service_date,printf('+%d days',3+(c.id*97+n.id*13)%63)),
       date(c.service_date,printf('+%d days',4+(c.id*97+n.id*13)%63+c.id%9)),
       CASE WHEN (c.id+n.id)%101=0 THEN 0 ELSE
       (450+(c.id*857+n.id*193+seed*97+c.month_id*c.member_id*219)%19000
        +m.propensity*110+CASE c.kind WHEN 0 THEN 8700 WHEN 1 THEN 1500 ELSE 700 END)
          *client.cost_factor/100 END
FROM claim c JOIN member m ON m.client_id=c.client_id AND m.id=c.member_id
JOIN client ON client.id=c.client_id CROSS JOIN config
CROSS JOIN (SELECT id FROM numbers WHERE id<=2) n
WHERE n.id=1 OR (c.kind<>2 AND c.id%3<>0);
INSERT INTO payment_event
SELECT claim_id,line_no,2,date(paid_date,'+5 days'),date(received_date,'+12 days'),
       CASE WHEN claim_id%31=0 THEN -delta_cents ELSE -(delta_cents/4) END
FROM payment_event WHERE claim_id%19=0 OR claim_id%31=0;

-- Raw deliveries carry replacement amounts. The audit ledger retains signed deltas.
CREATE TABLE claim_delivery(
    id INTEGER PRIMARY KEY,claim_id INTEGER REFERENCES claim(id),line_no INTEGER,version INTEGER,
    received_date TEXT NOT NULL, replacement_cents INTEGER NOT NULL CHECK(replacement_cents>=0)
);
INSERT INTO claim_delivery(claim_id,line_no,version,received_date,replacement_cents)
SELECT claim_id,line_no,version,received_date,
       SUM(delta_cents) OVER (PARTITION BY claim_id,line_no ORDER BY version)
FROM payment_event;
INSERT INTO claim_delivery(claim_id,line_no,version,received_date,replacement_cents)
SELECT claim_id,line_no,version,received_date,replacement_cents FROM claim_delivery WHERE id%23=0;
CREATE INDEX delivery_versions ON claim_delivery(claim_id,line_no,version DESC);
CREATE INDEX claim_member_period ON claim(client_id,member_id,month_id);

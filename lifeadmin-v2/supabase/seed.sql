-- Optional demo data. Replace 111111111 with YOUR Telegram numeric id (message @userinfobot).
with u as (
  insert into users (telegram_id, name) values (111111111, 'Demo')
  on conflict (telegram_id) do update set name = excluded.name
  returning id
)
insert into items (user_id, name, category, store, purchase_date, warranty_months, expiry_date, amount)
select u.id, v.name, v.category, v.store, v.pd::date, v.wm, v.exp::date, v.amount from u, (values
  ('Samsung 43" TV',  'electronics',  'Croma',        current_date - interval '23 months', 24, current_date + 7,   32999),
  ('Prestige Mixer',  'appliance',    'Reliance',     current_date - interval '11 months', 12, current_date + 1,    4499),
  ('Laptop',          'electronics',  'Amazon',       current_date - interval '6 months',  12, current_date + 30,  58990),
  ('Bike insurance',  'insurance',    'PolicyBazaar', current_date - interval '11 months', 12, current_date + 20,   2100),
  ('Netflix',         'subscription', 'Netflix',      current_date - interval '1 month',    1, current_date + 5,     649),
  ('Refrigerator',    'appliance',    'Vijay Sales',  current_date - interval '2 months',  60, current_date + 1700, 27500)
) as v(name, category, store, pd, wm, exp, amount);

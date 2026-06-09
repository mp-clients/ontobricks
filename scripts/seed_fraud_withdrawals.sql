-- scripts/seed_fraud_withdrawals.sql
-- Sample risky withdrawals for the fraud POC. Load into the catalog/schema the
-- fraud domain's R2RML mapping reads from. Adjust the fully-qualified name to the
-- target client (e.g. sandbox.fraud.withdrawals).
CREATE TABLE IF NOT EXISTS fraud_withdrawals (
    withdrawal_id text PRIMARY KEY,
    account_id    text NOT NULL,
    amount        numeric NOT NULL,
    channel       text NOT NULL,
    device        text,
    geo           text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

INSERT INTO fraud_withdrawals (withdrawal_id, account_id, amount, channel, device, geo) VALUES
  ('W1001', 'ACC-001', 95000, 'atm',    'new-device', 'MX-DF'),
  ('W1002', 'ACC-002',  4200, 'transfer','known',     'MX-NL'),
  ('W1003', 'ACC-003', 75000, 'transfer','new-device','US-TX')
ON CONFLICT (withdrawal_id) DO NOTHING;

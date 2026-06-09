-- scripts/seed_fraud_transactions.sql
-- Sample risky transactions for the fraud POC. Load into the catalog/schema the
-- fraud domain's R2RML mapping reads from. Adjust the fully-qualified name to the
-- target client (e.g. sandbox.fraud.transactions).
CREATE TABLE IF NOT EXISTS fraud_transactions (
    transaction_id text PRIMARY KEY,
    account_id    text NOT NULL,
    txn_type      text NOT NULL,  -- 'withdrawal' | 'transfer' | 'card_payment' ...
    direction     text NOT NULL,  -- 'outbound' | 'inbound' (fraud review targets outbound)
    amount        numeric NOT NULL,
    channel       text NOT NULL,
    device        text,
    geo           text,
    created_at    timestamptz NOT NULL DEFAULT now()
);

INSERT INTO fraud_transactions (transaction_id, account_id, txn_type, direction, amount, channel, device, geo) VALUES
  ('T1001', 'ACC-001', 'withdrawal', 'outbound', 95000, 'atm',     'new-device', 'MX-DF'),
  ('T1002', 'ACC-002', 'transfer',   'outbound',  4200, 'app',     'known',      'MX-NL'),
  ('T1003', 'ACC-003', 'withdrawal', 'outbound', 75000, 'branch',  'new-device', 'US-TX')
ON CONFLICT (transaction_id) DO NOTHING;

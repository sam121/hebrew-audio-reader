CREATE TABLE IF NOT EXISTS transactions (
  transaction_id VARCHAR PRIMARY KEY,
  owner VARCHAR,
  institution VARCHAR,
  account_id VARCHAR,
  account_name VARCHAR,
  account_type VARCHAR,
  date DATE,
  posted_date DATE,
  description_raw VARCHAR,
  description_clean VARCHAR,
  merchant VARCHAR,
  amount DECIMAL(38, 10),
  currency VARCHAR,
  amount_sgd DECIMAL(38, 10),
  fx_date DATE,
  fx_rate_to_sgd DECIMAL(38, 10),
  fx_source VARCHAR,
  fx_confidence VARCHAR,
  direction VARCHAR,
  category VARCHAR,
  subcategory VARCHAR,
  is_transfer_candidate BOOLEAN,
  matched_transfer_id VARCHAR,
  confidence_status VARCHAR,
  source_file VARCHAR,
  source_page VARCHAR,
  source_row VARCHAR,
  parser_name VARCHAR,
  parse_confidence DOUBLE
);

CREATE TABLE IF NOT EXISTS balances (
  balance_id VARCHAR PRIMARY KEY,
  owner VARCHAR,
  institution VARCHAR,
  account_id VARCHAR,
  account_name VARCHAR,
  account_type VARCHAR,
  date DATE,
  balance DECIMAL(38, 10),
  currency VARCHAR,
  balance_sgd DECIMAL(38, 10),
  fx_date DATE,
  fx_rate_to_sgd DECIMAL(38, 10),
  fx_source VARCHAR,
  fx_confidence VARCHAR,
  balance_type VARCHAR,
  confidence_status VARCHAR,
  source_file VARCHAR,
  source_page VARCHAR,
  source_row VARCHAR,
  parser_name VARCHAR,
  parse_confidence DOUBLE
);

CREATE TABLE IF NOT EXISTS holdings (
  holding_id VARCHAR PRIMARY KEY,
  owner VARCHAR,
  institution VARCHAR,
  account_id VARCHAR,
  date DATE,
  symbol VARCHAR,
  name VARCHAR,
  asset_class VARCHAR,
  quantity DECIMAL(38, 10),
  price DECIMAL(38, 10),
  market_value DECIMAL(38, 10),
  currency VARCHAR,
  market_value_sgd DECIMAL(38, 10),
  fx_date DATE,
  fx_rate_to_sgd DECIMAL(38, 10),
  fx_source VARCHAR,
  fx_confidence VARCHAR,
  confidence_status VARCHAR,
  source_file VARCHAR,
  source_row VARCHAR,
  parser_name VARCHAR
);

CREATE TABLE IF NOT EXISTS transfers (
  transfer_id VARCHAR PRIMARY KEY,
  owner VARCHAR,
  from_transaction_id VARCHAR,
  to_transaction_id VARCHAR,
  from_account VARCHAR,
  to_account VARCHAR,
  from_date DATE,
  to_date DATE,
  from_amount DECIMAL(38, 10),
  from_currency VARCHAR,
  to_amount DECIMAL(38, 10),
  to_currency VARCHAR,
  implied_fx_rate DECIMAL(38, 10),
  match_confidence DOUBLE,
  match_reason VARCHAR,
  status VARCHAR
);

CREATE TABLE IF NOT EXISTS source_limitations (
  owner VARCHAR,
  institution VARCHAR,
  account_id VARCHAR,
  known_account_existed_before_available_records BOOLEAN,
  earliest_available_record_date DATE,
  likely_reason VARCHAR,
  notes VARCHAR
);

CREATE TABLE IF NOT EXISTS issues (
  issue_id VARCHAR PRIMARY KEY,
  issue_type VARCHAR,
  severity VARCHAR,
  owner VARCHAR,
  institution VARCHAR,
  account_id VARCHAR,
  date DATE,
  source_file VARCHAR,
  source_page VARCHAR,
  message VARCHAR,
  suggested_action VARCHAR,
  status VARCHAR
);

CREATE TABLE IF NOT EXISTS inventory_files (
  inventory_id VARCHAR PRIMARY KEY,
  path VARCHAR,
  owner VARCHAR,
  institution VARCHAR,
  file_type VARCHAR,
  parsed_date DATE,
  modified_at VARCHAR,
  size_bytes BIGINT,
  content_hash VARCHAR,
  detected_account_id VARCHAR,
  statement_type VARCHAR,
  statement_period_start DATE,
  statement_period_end DATE,
  duplicate_hash_group VARCHAR,
  duplicate_statement_group VARCHAR,
  overlap_group VARCHAR,
  missing_month_candidate BOOLEAN,
  notes VARCHAR
);

CREATE TABLE IF NOT EXISTS run_control_totals (
  control_id VARCHAR PRIMARY KEY,
  parser_name VARCHAR,
  source_file VARCHAR,
  owner VARCHAR,
  institution VARCHAR,
  account_id VARCHAR,
  file_count BIGINT,
  row_count BIGINT,
  date_min DATE,
  date_max DATE,
  sum_credits DECIMAL(38, 10),
  sum_debits DECIMAL(38, 10),
  opening_balance DECIMAL(38, 10),
  closing_balance DECIMAL(38, 10),
  warning_count BIGINT,
  failed_row_count BIGINT
);

CREATE TABLE IF NOT EXISTS fx_rates (
  date DATE,
  currency VARCHAR,
  rate_to_sgd DECIMAL(38, 12),
  fx_source VARCHAR,
  fx_confidence VARCHAR,
  ecb_eur_rate DECIMAL(38, 12),
  ecb_sgd_rate DECIMAL(38, 12),
  source_url VARCHAR,
  notes VARCHAR
);

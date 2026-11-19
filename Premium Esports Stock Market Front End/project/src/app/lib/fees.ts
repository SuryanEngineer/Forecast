/** The transaction fee charged to the TAKER of a trade (backend platform parameter fees.transaction_fee_pct).
 * Text that states the fee (the Guide, the intro tour) reads it from here so it is changed in one place. Trade tickets show
 * the exact fee for the order from the server's quote, so they never use this. */
export const TRANSACTION_FEE = 0.001;
export const TRANSACTION_FEE_LABEL = '0.1%';

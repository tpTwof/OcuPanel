export function followupSummary(referrals, now) {
  const pending = referrals.filter((referral) => referral.status !== 'arrived')
  return {
    pending: pending.length,
    overdue: pending.some((referral) => Date.parse(referral.due_at) < now)
  }
}

export function followupCases(cases, filter, now) {
  const rows = cases.map((item) => ({ item, ...followupSummary(item.referrals, now) }))
  if (filter === 'pending') return rows.filter((row) => row.pending > 0)
  if (filter === 'overdue') return rows.filter((row) => row.overdue)
  return rows
}

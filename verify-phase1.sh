#!/usr/bin/env bash
# Phase 1 Verification Script
BASE="http://localhost:18791"
PASS=0; FAIL=0

check() {
  local desc="$1" result="$2" expected="$3"
  if echo "$result" | grep -q "$expected"; then
    echo "✅ $desc"; PASS=$((PASS+1))
  else
    echo "❌ $desc (got: $result)"; FAIL=$((FAIL+1))
  fi
}

echo "=== Phase 1 验收 ==="

# 1. Create agent A (100 tokens)
R=$(curl -s -X POST "$BASE/admin/add-agent" -H "Content-Type: application/json" \
  -d '{"id":"agent_a","name":"Agent A","model_id":"claude-sonnet","model_family":"claude","tokens":100}')
check "创建 Agent A" "$R" '"ok":true'

# 2. Create agent B (100 tokens)
R=$(curl -s -X POST "$BASE/admin/add-agent" -H "Content-Type: application/json" \
  -d '{"id":"agent_b","name":"Agent B","model_id":"gpt-4","model_family":"gpt","tokens":100}')
check "创建 Agent B" "$R" '"ok":true'

# 3. /economy returns both agents
R=$(curl -s "$BASE/economy")
check "/economy 返回 Agent A" "$R" '"agent_a"'
check "/economy 返回 Agent B" "$R" '"agent_b"'

# 4. Admin set-token: A -> 150
R=$(curl -s -X POST "$BASE/admin/set-token" -H "Content-Type: application/json" \
  -d '{"agentId":"agent_a","tokens":150}')
check "admin set-token A=150" "$R" '"tokens":150'

# 5. Ledger has record
R=$(curl -s "$BASE/ledger")
check "ledger 有 admin_adjust 记录" "$R" '"admin_adjust"'
check "ledger 有 init 记录" "$R" '"init"'

# 6. /economy shows A=150
R=$(curl -s "$BASE/economy")
check "Economy: A 有 150 tokens" "$R" '150'

# 7. version field exists
check "Agent 有 version 字段" "$R" '"version"'
check "Agent 有 updated_at 字段" "$R" '"updated_at"'

echo ""
echo "=== 结果: $PASS 通过 / $FAIL 失败 ==="

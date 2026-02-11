#!/bin/bash
# Count core agent lines (excluding adapters: channels/, cli/, infra/providers)
cd "$(dirname "$0")" || exit 1

echo "HaL Core Agent Line Count"
echo "================================"
echo ""

# Core modules to count
for dir in core bus capabilities session utils; do
  if [ -d "hal/$dir" ]; then
    count=$(find "hal/$dir" -name "*.py" -exec cat {} + 2>/dev/null | wc -l)
    printf "  %-20s %6s lines\n" "$dir/" "$count"
  fi
done

# Root files
root=$(cat hal/__init__.py hal/__main__.py 2>/dev/null | wc -l)
printf "  %-20s %6s lines\n" "(root)" "$root"

echo ""

# Calculate total excluding adapters (channels, cli) and external (providers)
total=$(find hal -name "*.py" \
  ! -path "*/channels/*" \
  ! -path "*/cli/*" \
  ! -path "*/providers/*" \
  ! -path "*/__pycache__/*" \
  2>/dev/null | xargs cat | wc -l)
printf "%-22s %6s lines\n" "Core total:" "$total"
echo ""
echo "  (excludes: channels/, cli/, infra/providers/)"

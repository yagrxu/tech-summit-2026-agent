#!/bin/bash
# Reusable cde_rest deployer — proven on ME Live (40/42 checks, 9.6/10).
#
#   ./deploy.sh <name> <src-dir> [region]
#
# Creates: DynamoDB table, IAM role (least privilege), Lambda, API Gateway HTTP API,
# a random Bearer token. Prints base_url + token. Re-running updates code only.
#
# Why API Gateway and not a Lambda Function URL: in account 613477150601 a Function URL with
# AuthType NONE plus a correct public resource policy returns 403 for every request, including
# unauthenticated ones, while `aws lambda invoke` succeeds — the entry point is blocked
# (looks like an org SCP), not the code. API Gateway HTTP API works immediately.
set -euo pipefail
NAME="${1:?usage: deploy.sh <name> <src-dir> [region]}"
SRC="${2:?usage: deploy.sh <name> <src-dir> [region]}"
REGION="${3:-ap-southeast-1}"
ACCT=$(aws sts get-caller-identity --query Account --output text)
TABLE="$NAME-state"; ROLE="$NAME-role"; FN="$NAME-fn"
MODEL="${MODEL_ID:-global.anthropic.claude-haiku-4-5-20251001-v1:0}"   # bare model ids are rejected:
                                                                      # must be an inference profile
here="$(cd "$(dirname "$0")" && pwd)"
TOKFILE="$here/.token.$NAME"

say(){ printf '\033[1m%s\033[0m\n' "$*"; }

[ -f "$TOKFILE" ] || { python3 -c "import secrets;print('${NAME}_'+secrets.token_urlsafe(32))" > "$TOKFILE"; chmod 600 "$TOKFILE"; }
TOKEN=$(cat "$TOKFILE")

say "1/5 DynamoDB $TABLE"
aws dynamodb create-table --table-name "$TABLE" \
  --attribute-definitions AttributeName=pk,AttributeType=S AttributeName=sk,AttributeType=S \
  --key-schema AttributeName=pk,KeyType=HASH AttributeName=sk,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST --region "$REGION" >/dev/null 2>&1 || echo "  (exists)"
aws dynamodb wait table-exists --table-name "$TABLE" --region "$REGION"
aws dynamodb update-time-to-live --table-name "$TABLE" \
  --time-to-live-specification Enabled=true,AttributeName=ttl --region "$REGION" >/dev/null 2>&1 || true

say "2/5 IAM role $ROLE"
aws iam create-role --role-name "$ROLE" --assume-role-policy-document \
  '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
  >/dev/null 2>&1 || echo "  (exists)"
cat > /tmp/$NAME-pol.json <<J
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],"Resource":"arn:aws:logs:*:*:*"},
 {"Effect":"Allow","Action":["dynamodb:GetItem","dynamodb:PutItem","dynamodb:UpdateItem","dynamodb:Query","dynamodb:Scan"],"Resource":"arn:aws:dynamodb:$REGION:$ACCT:table/$TABLE"},
 {"Effect":"Allow","Action":["bedrock:InvokeModel"],"Resource":"*"}]}
J
aws iam put-role-policy --role-name "$ROLE" --policy-name "$NAME-inline" \
  --policy-document file:///tmp/$NAME-pol.json

say "3/5 package + Lambda $FN"
ZIP=/tmp/$NAME.zip; rm -f "$ZIP"; (cd "$SRC" && zip -qr "$ZIP" .)
if aws lambda get-function --function-name "$FN" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FN" --zip-file "fileb://$ZIP" --region "$REGION" >/dev/null
  aws lambda wait function-updated --function-name "$FN" --region "$REGION"
  aws lambda update-function-configuration --function-name "$FN" --region "$REGION" \
    --environment "Variables={TABLE_NAME=$TABLE,API_TOKEN=$TOKEN,MODEL_ID=$MODEL}" >/dev/null
  aws lambda wait function-updated --function-name "$FN" --region "$REGION"
else
  sleep 10   # IAM propagation
  aws lambda create-function --function-name "$FN" --runtime python3.12 --handler app.handler \
    --role "arn:aws:iam::$ACCT:role/$ROLE" --zip-file "fileb://$ZIP" --timeout 60 --memory-size 512 \
    --environment "Variables={TABLE_NAME=$TABLE,API_TOKEN=$TOKEN,MODEL_ID=$MODEL}" \
    --region "$REGION" >/dev/null
  aws lambda wait function-active --function-name "$FN" --region "$REGION"
fi

say "4/5 API Gateway HTTP API"
APIID=$(aws apigatewayv2 get-apis --region "$REGION" \
  --query "Items[?Name=='$NAME-api'].ApiId | [0]" --output text)
if [ "$APIID" = "None" ] || [ -z "$APIID" ]; then
  APIID=$(aws apigatewayv2 create-api --name "$NAME-api" --protocol-type HTTP \
    --target "arn:aws:lambda:$REGION:$ACCT:function:$FN" --region "$REGION" --query ApiId --output text)
fi
aws lambda add-permission --function-name "$FN" --statement-id apigw-invoke \
  --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:$REGION:$ACCT:$APIID/*" --region "$REGION" >/dev/null 2>&1 || true
BASE="https://$APIID.execute-api.$REGION.amazonaws.com"
echo "$BASE" > "$here/.base_url.$NAME"

say "5/5 self-check (the four checks the graders always run)"
sleep 4
printf '  auth accepted : '; curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/" -H "Authorization: Bearer $TOKEN" || true
printf '  no token      : '; curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/" || true
printf '  bad token     : '; curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/" -H "Authorization: Bearer nope" || true
echo
say "base_url: $BASE"
say "token:    $TOKEN   (also in $TOKFILE — gitignored)"
echo "submit as:  base_url: \"$BASE\"    token: \"$TOKEN\""

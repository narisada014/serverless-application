import boto3
from me_alias_create import MeAliasCreate

dynamodb = boto3.resource('dynamodb')


def lambda_handler(event, context):
    me_alias_create = MeAliasCreate(event=event, context=context, dynamodb=dynamodb)
    return me_alias_create.main()
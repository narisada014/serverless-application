import os
import settings
import logging
import traceback
import secrets
from lambda_base import LambdaBase
from twitter_util import TwitterUtil
from user_util import UserUtil
from jsonschema import validate, ValidationError
from botocore.exceptions import ClientError
from exceptions import TwitterOauthError
from response_builder import ResponseBuilder


class LoginTwitterIndex(LambdaBase):
    def get_schema(self):
        return {
            'type': 'object',
            'properties': {
                'oauth_token': settings.parameters['oauth_token'],
                'oauth_verifier': settings.parameters['oauth_verifier']
            },
            'required': ['oauth_token', 'oauth_verifier']
        }

    def validate_params(self):
        if not self.event.get('body'):
            raise ValidationError('Request parameter is required')
        validate(self.params, self.get_schema())

    def exec_main_proc(self):
        twitter = TwitterUtil(
            consumer_key=os.environ['TWITTER_CONSUMER_KEY'],
            consumer_secret=os.environ['TWITTER_CONSUMER_SECRET']
        )
        try:
            user_info = twitter.get_user_info(
                oauth_token=self.params['oauth_token'],
                oauth_verifier=self.params['oauth_verifier']
            )
        except TwitterOauthError as e:
            if e.status_code == 401:
                return ResponseBuilder.response(
                    status_code=401,
                    body={'message': e.message}
                )
            logging.info(self.event)
            logging.fatal(e)
            traceback.print_exc()
            return ResponseBuilder.response(
                status_code=500,
                body={'message': 'Internal server error'}
            )
        if UserUtil.exists_user(self.dynamodb, user_info['user_id']):

            try:
                has_alias_user_id = UserUtil.has_alias_user_id(
                    dynamodb=self.dynamodb,
                    user_id=user_info['user_id'],
                )
                if has_alias_user_id is True:
                    user_id = UserUtil.get_alias_user_id(
                        dynamodb=self.dynamodb,
                        user_id=user_info['user_id']
                    )
                else:
                    user_id = user_info['user_id']

                # パスワードの取得、デコード処理追加
                sns_users = self.dynamodb.Table(os.environ['SNS_USERS_TABLE_NAME'])
                sns_user = sns_users.get_item(Key={'user_id': user_info['user_id']}).get('Item')
                hash_data = sns_user['password']
                byte_hash_data = hash_data.encode()
                password = UserUtil.decrypt_password(byte_hash_data)

                response = UserUtil.sns_login(
                    cognito=self.cognito,
                    user_pool_id=os.environ['COGNITO_USER_POOL_ID'],
                    user_pool_app_id=os.environ['COGNITO_USER_POOL_APP_ID'],
                    user_id=user_id,
                    password=password,
                    provider=os.environ['THIRD_PARTY_LOGIN_MARK']
                )
                return ResponseBuilder.response(
                    status_code=200,
                    body={
                        'access_token': response['AuthenticationResult']['AccessToken'],
                        'id_token': response['AuthenticationResult']['IdToken'],
                        'refresh_token': response['AuthenticationResult']['RefreshToken'],
                        'last_auth_user': user_id,
                        'has_alias_user_id': has_alias_user_id,
                        'status': 'login'
                    }
                )
            except ClientError as e:
                logging.info(self.event)
                logging.fatal(e)
                traceback.print_exc()
                return ResponseBuilder.response(
                    status_code=500,
                    body={'message': 'Internal server error'}
                )

        try:
            backed_temp_password = os.environ['SNS_LOGIN_COMMON_TEMP_PASSWORD']
            backed_password = secrets.token_hex(settings.TOKEN_SEED_BYTES)
            response = UserUtil.create_sns_user(
                cognito=self.cognito,
                user_pool_id=os.environ['COGNITO_USER_POOL_ID'],
                user_pool_app_id=os.environ['COGNITO_USER_POOL_APP_ID'],
                user_id=user_info['user_id'],
                email=user_info['email'],
                backed_temp_password=backed_temp_password,
                backed_password=backed_password,
                provider=os.environ['THIRD_PARTY_LOGIN_MARK']
            )

            password_hash = UserUtil.encrypt_password(backed_password)

            UserUtil.add_sns_user_info(
                dynamodb=self.dynamodb,
                user_id=user_info['user_id'],
                password=password_hash,
                email=user_info['email'],
                user_display_name=user_info['display_name'],
                icon_image_url=user_info['icon_image_url']
            )
            return ResponseBuilder.response(
                status_code=200,
                body={
                    'access_token': response['AuthenticationResult']['AccessToken'],
                    'id_token': response['AuthenticationResult']['IdToken'],
                    'refresh_token': response['AuthenticationResult']['RefreshToken'],
                    'last_auth_user': user_info['user_id'],
                    'has_alias_user_id': False,
                    'status': 'sign_up'
                }
            )

        except ClientError as e:
            logging.info(self.event)
            logging.fatal(e)
            traceback.print_exc()
            if e.response['Error']['Code'] == 'UsernameExistsException':
                return ResponseBuilder.response(
                    status_code=400,
                    body={'message': 'EmailExistsException'}
                )
            return ResponseBuilder.response(
                status_code=500,
                body={'message': 'Internal server error'}
            )
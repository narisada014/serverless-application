import json
import os
import boto3
import time

from elasticsearch import Elasticsearch
from tests_es_util import TestsEsUtil

import settings
from boto3.dynamodb.conditions import Key
from unittest import TestCase
from me_articles_public_republish import MeArticlesPublicRepublish
from unittest.mock import patch, MagicMock
from tests_util import TestsUtil

from tag_util import TagUtil


class TestMeArticlesPublicRepublish(TestCase):
    dynamodb = boto3.resource('dynamodb', endpoint_url='http://localhost:4569/')
    elasticsearch = Elasticsearch(
        hosts=[{'host': 'localhost'}]
    )

    @classmethod
    def setUpClass(cls):
        TestsUtil.set_all_tables_name_to_env()

        cls.article_info_table = cls.dynamodb.Table('ArticleInfo')
        cls.article_content_table = cls.dynamodb.Table('ArticleContent')
        cls.article_content_edit_table = cls.dynamodb.Table('ArticleContentEdit')
        cls.article_history_table = cls.dynamodb.Table('ArticleHistory')

    def setUp(self):
        TestsUtil.delete_all_tables(self.dynamodb)

        article_info_items = [
            {
                'article_id': 'publicId0001',
                'user_id': 'test01',
                'status': 'public',
                'topic': 'fashion',
                'tags': ['a', 'b', 'c'],
                'sort_key': 1520150272000000
            },
            {
                'article_id': 'publicId0002',
                'user_id': 'test01',
                'status': 'public',
                'topic': 'fashion',
                'sort_key': 1520150272000000
            }
        ]
        TestsUtil.create_table(self.dynamodb, os.environ['ARTICLE_INFO_TABLE_NAME'], article_info_items)

        article_content_items = [
            {
                'article_id': 'publicId0001',
                'title': 'sample_title1',
                'body': 'sample_body1'
            },
            {
                'article_id': 'publicId0002',
                'title': 'sample_title2',
                'body': 'sample_body2'
            }
        ]
        TestsUtil.create_table(self.dynamodb, os.environ['ARTICLE_CONTENT_TABLE_NAME'], article_content_items)

        article_content_edit_items = [
            {
                'article_id': 'publicId0001',
                'user_id': 'test01',
                'title': 'edit_title1_edit',
                'body': 'edit_body1_edit',
                'overview': 'edit_overview1_edit',
                'eye_catch_url': 'http://example.com/eye_catch_url_edit'
            }
        ]
        TestsUtil.create_table(self.dynamodb, os.environ['ARTICLE_CONTENT_EDIT_TABLE_NAME'], article_content_edit_items)

        article_history_items = [
            {
                'article_id': 'publicId0001',
                'title': 'sample_title1_history',
                'body': 'sample_body1_history',
                'created_at': int(time.time()) - 1
            }
        ]
        TestsUtil.create_table(self.dynamodb, os.environ['ARTICLE_HISTORY_TABLE_NAME'], article_history_items)

        topic_items = [
            {'name': 'crypto', 'order': 1, 'index_hash_key': settings.TOPIC_INDEX_HASH_KEY},
            {'name': 'fashion', 'order': 2, 'index_hash_key': settings.TOPIC_INDEX_HASH_KEY},
            {'name': 'food', 'order': 3, 'index_hash_key': settings.TOPIC_INDEX_HASH_KEY}
        ]
        TestsUtil.create_table(self.dynamodb, os.environ['TOPIC_TABLE_NAME'], topic_items)

        TestsEsUtil.create_tag_index(self.elasticsearch)
        self.elasticsearch.indices.refresh(index="tags")

    def tearDown(self):
        TestsUtil.delete_all_tables(self.dynamodb)
        self.elasticsearch.indices.delete(index="tags", ignore=[404])

    def assert_bad_request(self, params):
        function = MeArticlesPublicRepublish(params, {}, dynamodb=self.dynamodb, elasticsearch=self.elasticsearch)
        response = function.main()

        self.assertEqual(response['statusCode'], 400)

    def test_main_ok(self):
        TagUtil.create_tag(self.elasticsearch, 'a')
        TagUtil.create_tag(self.elasticsearch, 'B')
        self.elasticsearch.indices.refresh(index='tags')

        params = {
            'pathParameters': {
                'article_id': 'publicId0001'
            },
            'body': {
                'topic': 'crypto',
                'tags': ['A', 'B', 'C', 'D', 'E' * 25]
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        article_info_before = self.article_info_table.scan()['Items']
        article_content_before = self.article_content_table.scan()['Items']
        article_content_edit_before = self.article_content_edit_table.scan()['Items']
        article_history_before = self.article_history_table.scan()['Items']

        response = MeArticlesPublicRepublish(params, {}, dynamodb=self.dynamodb, elasticsearch=self.elasticsearch).main()

        article_info_after = self.article_info_table.scan()['Items']
        article_content_after = self.article_content_table.scan()['Items']
        article_content_edit_after = self.article_content_edit_table.scan()['Items']
        article_history_after = self.article_history_table.scan()['Items']

        article_info = self.article_info_table.get_item(Key={'article_id': params['pathParameters']['article_id']})['Item']
        article_content = self.article_content_table.get_item(
            Key={'article_id': params['pathParameters']['article_id']}
        )['Item']
        article_history = self.article_history_table.query(
            KeyConditionExpression=Key('article_id').eq(params['pathParameters']['article_id'])
        )['Items'][-1]

        expected_item = {
            'article_id': 'publicId0001',
            'user_id': 'test01',
            'title': 'edit_title1_edit',
            'body': 'edit_body1_edit',
            'overview': 'edit_overview1_edit',
            'eye_catch_url': 'http://example.com/eye_catch_url_edit',
            'topic': 'crypto',
            'tags': ['a', 'B', 'C', 'D', 'E' * 25]
        }

        article_info_param_names = ['eye_catch_url', 'title', 'overview']
        article_content_param_names = ['title', 'body']

        self.assertEqual(response['statusCode'], 200)
        self.assertEqual(article_info['status'], 'public')
        self.assertEqual(article_info['sync_elasticsearch'], 1)
        self.assertEqual(params['requestContext']['authorizer']['claims']['cognito:username'], article_info['user_id'])
        for key in article_info_param_names:
            self.assertEqual(expected_item[key], article_info[key])

        for key in article_content_param_names:
            self.assertEqual(expected_item[key], article_content[key])
            self.assertEqual(expected_item[key], article_history[key])

        self.assertEqual(len(article_info_after) - len(article_info_before), 0)
        self.assertEqual(len(article_content_after) - len(article_content_before), 0)
        self.assertEqual(len(article_content_edit_after) - len(article_content_edit_before), -1)
        self.assertEqual(len(article_history_after) - len(article_history_before), 1)

    def test_main_ok_with_no_article_content_edit(self):
        params = {
            'pathParameters': {
                'article_id': 'publicId0002'
            },
            'body': {
                'topic': 'crypto'
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        article_info_before = self.article_info_table.scan()['Items']
        article_content_before = self.article_content_table.scan()['Items']
        article_content_edit_before = self.article_content_edit_table.scan()['Items']
        article_history_before = self.article_history_table.scan()['Items']

        response = MeArticlesPublicRepublish(params, {}, dynamodb=self.dynamodb, elasticsearch=self.elasticsearch).main()

        article_info_after = self.article_info_table.scan()['Items']
        article_content_after = self.article_content_table.scan()['Items']
        article_content_edit_after = self.article_content_edit_table.scan()['Items']
        article_history_after = self.article_history_table.scan()['Items']

        self.assertEqual(response['statusCode'], 404)
        self.assertEqual(len(article_info_after) - len(article_info_before), 0)
        self.assertEqual(len(article_content_after) - len(article_content_before), 0)
        self.assertEqual(len(article_content_edit_after) - len(article_content_edit_before), 0)
        self.assertEqual(len(article_history_after) - len(article_history_before), 0)

    def test_main_ng_with_none_title(self):
        params = {
            'pathParameters': {
                'article_id': 'publicId0001'
            },
            'body': {
                'topic': 'crypto'
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        self.article_content_edit_table.update_item(
            Key={'article_id': params['pathParameters']['article_id']},
            UpdateExpression="set title = :title",
            ExpressionAttributeValues={':title': None}
        )

        article_info_before = self.article_info_table.scan()['Items']
        article_content_before = self.article_content_table.scan()['Items']
        article_content_edit_before = self.article_content_edit_table.scan()['Items']
        article_history_before = self.article_history_table.scan()['Items']

        response = MeArticlesPublicRepublish(params, {}, dynamodb=self.dynamodb, elasticsearch=self.elasticsearch).main()

        article_info_after = self.article_info_table.scan()['Items']
        article_content_after = self.article_content_table.scan()['Items']
        article_content_edit_after = self.article_content_edit_table.scan()['Items']
        article_history_after = self.article_history_table.scan()['Items']

        self.assertEqual(response['statusCode'], 400)
        self.assertEqual(len(article_info_after) - len(article_info_before), 0)
        self.assertEqual(len(article_content_after) - len(article_content_before), 0)
        self.assertEqual(len(article_content_edit_after) - len(article_content_edit_before), 0)
        self.assertEqual(len(article_history_after) - len(article_history_before), 0)

    def test_main_ng_with_none_body(self):
        params = {
            'pathParameters': {
                'article_id': 'publicId0001'
            },
            'body': {
                'topic': 'crypto'
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        self.article_content_edit_table.update_item(
            Key={'article_id': params['pathParameters']['article_id']},
            UpdateExpression="set body = :body",
            ExpressionAttributeValues={':body': None}
        )

        article_info_before = self.article_info_table.scan()['Items']
        article_content_before = self.article_content_table.scan()['Items']
        article_content_edit_before = self.article_content_edit_table.scan()['Items']
        article_history_before = self.article_history_table.scan()['Items']

        response = MeArticlesPublicRepublish(params, {}, dynamodb=self.dynamodb, elasticsearch=self.elasticsearch).main()

        article_info_after = self.article_info_table.scan()['Items']
        article_content_after = self.article_content_table.scan()['Items']
        article_content_edit_after = self.article_content_edit_table.scan()['Items']
        article_history_after = self.article_history_table.scan()['Items']

        self.assertEqual(response['statusCode'], 400)
        self.assertEqual(len(article_info_after) - len(article_info_before), 0)
        self.assertEqual(len(article_content_after) - len(article_content_before), 0)
        self.assertEqual(len(article_content_edit_after) - len(article_content_edit_before), 0)
        self.assertEqual(len(article_history_after) - len(article_history_before), 0)

    def test_main_ng_with_none_overview(self):
        params = {
            'pathParameters': {
                'article_id': 'publicId0001'
            },
            'body': {
                'topic': 'crypto'
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        self.article_content_edit_table.update_item(
            Key={'article_id': params['pathParameters']['article_id']},
            UpdateExpression="set overview = :overview",
            ExpressionAttributeValues={':overview': None}
        )

        article_info_before = self.article_info_table.scan()['Items']
        article_content_before = self.article_content_table.scan()['Items']
        article_content_edit_before = self.article_content_edit_table.scan()['Items']
        article_history_before = self.article_history_table.scan()['Items']

        response = MeArticlesPublicRepublish(params, {}, dynamodb=self.dynamodb, elasticsearch=self.elasticsearch).main()

        article_info_after = self.article_info_table.scan()['Items']
        article_content_after = self.article_content_table.scan()['Items']
        article_content_edit_after = self.article_content_edit_table.scan()['Items']
        article_history_after = self.article_history_table.scan()['Items']

        self.assertEqual(response['statusCode'], 400)
        self.assertEqual(len(article_info_after) - len(article_info_before), 0)
        self.assertEqual(len(article_content_after) - len(article_content_before), 0)
        self.assertEqual(len(article_content_edit_after) - len(article_content_edit_before), 0)
        self.assertEqual(len(article_history_after) - len(article_history_before), 0)

    @patch("me_articles_public_republish.TagUtil.create_and_count", MagicMock(side_effect=Exception()))
    def test_create_and_count_raise_exception(self):
        params = {
            'pathParameters': {
                'article_id': 'publicId0001'
            },
            'body': {
                'topic': 'crypto',
                'tags': ['A']
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        response = MeArticlesPublicRepublish(params, {}, dynamodb=self.dynamodb, elasticsearch=self.elasticsearch).main()

        self.assertEqual(response['statusCode'], 200)

    def test_call_tag_util_methods(self):
        params = {
            'pathParameters': {
                'article_id': 'publicId0001'
            },
            'body': {
                'topic': 'crypto',
                'tags': ['A']
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        mock_lib = MagicMock()
        mock_lib.get_tags_with_name_collation.return_value = ['A']
        with patch('me_articles_public_republish.TagUtil', mock_lib):
            MeArticlesPublicRepublish(params, {}, dynamodb=self.dynamodb, elasticsearch=self.elasticsearch).main()

            self.assertTrue(mock_lib.validate_format.called)
            args, _ = mock_lib.validate_format.call_args
            self.assertEqual(args[0], ['A'])

            self.assertTrue(mock_lib.get_tags_with_name_collation.called)
            args, _ = mock_lib.get_tags_with_name_collation.call_args
            self.assertEqual(args[1], ['A'])

            self.assertTrue(mock_lib.create_and_count.called)
            args, _ = mock_lib.create_and_count.call_args

            self.assertTrue(args[0])
            self.assertEqual(args[1], ['a', 'b', 'c'])
            self.assertEqual(args[2], ['A'])

    def test_call_validate_array_unique(self):
        params = {
            'pathParameters': {
                'article_id': 'publicId0001'
            },
            'body': {
                'topic': 'crypto',
                'tags': ['A', 'B', 'C', 'D', 'E' * 25]
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        mock_lib = MagicMock()

        with patch('me_articles_public_republish.ParameterUtil', mock_lib):
            MeArticlesPublicRepublish(params, {}, dynamodb=self.dynamodb, elasticsearch=self.elasticsearch).main()

            self.assertTrue(mock_lib.validate_array_unique.called)
            args, kwargs = mock_lib.validate_array_unique.call_args
            self.assertEqual(args[0], ['A', 'B', 'C', 'D', 'E' * 25])
            self.assertEqual(args[1], 'tags')
            self.assertEqual(kwargs['case_insensitive'], True)

    def test_call_validate_methods(self):
        params = {
            'pathParameters': {
                'article_id': 'publicId0001'
            },
            'body': {
                'topic': 'crypto'
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        mock_lib = MagicMock()
        with patch('me_articles_public_republish.DBUtil', mock_lib):
            MeArticlesPublicRepublish(params, {}, dynamodb=self.dynamodb, elasticsearch=self.elasticsearch).main()

            self.assertTrue(mock_lib.validate_article_existence.called)
            args, kwargs = mock_lib.validate_article_existence.call_args
            self.assertTrue(args[0])
            self.assertTrue(args[1])
            self.assertTrue(kwargs['user_id'])
            self.assertEqual(kwargs['status'], 'public')

            self.assertTrue(mock_lib.validate_topic.called)
            args, kwargs = mock_lib.validate_topic.call_args
            self.assertTrue(args[0])
            self.assertEqual(args[1], 'crypto')

    def test_validation_with_no_article_id(self):
        params = {
            'queryStringParameters': {},
            'body': {
                'topic': 'crypto'
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        self.assert_bad_request(params)

    def test_validation_article_id_max(self):
        params = {
            'queryStringParameters': {
                'article_id': 'A' * 13
            },
            'body': {
                'topic': 'crypto'
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        self.assert_bad_request(params)

    def test_validation_article_id_min(self):
        params = {
            'queryStringParameters': {
                'article_id': 'A' * 11
            },
            'body': {
                'topic': 'crypto'
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        self.assert_bad_request(params)

    def test_validation_with_no_topic(self):
        params = {
            'pathParameters': {
                'article_id': 'publicId0001'
            },
            'body': {},
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        self.assert_bad_request(params)

    def test_validation_topic_max(self):
        params = {
            'queryStringParameters': {
                'article_id': 'publicId0001'
            },
            'body': {
                'topic': 'A' * 21
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        self.assert_bad_request(params)

    def test_validation_many_tags(self):
        params = {
            'queryStringParameters': {
                'article_id': 'publicId0001',
            },
            'body': {
                'topic': 'crypto',
                'tags': ['A', 'B', 'C', 'D', 'E', 'F']
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        self.assert_bad_request(params)

    def test_validation_tag_name_max(self):
        params = {
            'queryStringParameters': {
                'article_id': 'publicId0001',
            },
            'body': {
                'topic': 'crypto',
                'tags': ['A', 'B', 'C', 'D', 'E' * 26]
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        self.assert_bad_request(params)

    def test_validation_tag_name_min(self):
        params = {
            'queryStringParameters': {
                'article_id': 'publicId0001',
            },
            'body': {
                'topic': 'crypto',
                'tags': ['A', 'B', 'C', 'D', '']
            },
            'requestContext': {
                'authorizer': {
                    'claims': {
                        'cognito:username': 'test01',
                        'phone_number_verified': 'true',
                        'email_verified': 'true'
                    }
                }
            }
        }
        params['body'] = json.dumps(params['body'])

        self.assert_bad_request(params)

import json
import unittest
from unittest.mock import Mock,patch
from gis_local_parser import parse_local_query


class LocalParserTests(unittest.TestCase):
    def test_deepseek_paraphrase_and_bounded_road_context(self):
        client=Mock()
        client.chat.completions.create.return_value.choices=[Mock(message=Mock(content=json.dumps(
            {'road_name':'交大东路','distance_m':500,'operation':'road_buffer_buildings'})))]
        with patch('gis_local_parser.make_client',return_value=client):
            task=parse_local_query('帮我看看交大东路附近500米有哪些建筑物',['5','交大东路','学院路'],'DeepSeek（API指令解析）')
        self.assertEqual((task.road_name,task.distance_m),('交大东路',500))
        self.assertNotIn('学院路',client.chat.completions.create.call_args.kwargs['messages'][0]['content'])

    def test_local_mode_never_creates_model_client(self):
        with patch('gis_local_parser.make_client',side_effect=AssertionError('API forbidden')):
            task=parse_local_query('分析交大东路周围500m范围的建筑物',['交大东路'],'本地规则（无需API）')
            self.assertEqual(task.distance_m,500)

    def test_unsupported_intent_and_wrong_model_distance_rejected(self):
        client=Mock()
        with patch('gis_local_parser.make_client',return_value=client):
            with self.assertRaises(ValueError):
                parse_local_query('分析交大东路周边500米范围的建筑物，计算平均高度',['交大东路'],'DeepSeek（API指令解析）')
            client.chat.completions.create.assert_not_called()
            client.chat.completions.create.return_value.choices=[Mock(message=Mock(content=json.dumps(
                {'road_name':'交大东路','distance_m':1000,'operation':'road_buffer_buildings'})))]
            with self.assertRaises(ValueError):
                parse_local_query('看看交大东路500米内的建筑物',['交大东路'],'DeepSeek（API指令解析）')


if __name__=='__main__':unittest.main()

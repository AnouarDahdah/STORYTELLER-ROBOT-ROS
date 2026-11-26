#!/usr/bin/env python3

import json
import sys
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class StorytellingNode(Node):
    def __init__(self):
        super().__init__('storytelling_node')
        self.declare_parameter('config', '/opt/imaginarium/raspberry_story/config.yaml')
        self.declare_parameter('language', 'it')
        self.declare_parameter('device_id', 'imaginarium-device')
        self.declare_parameter('conversation_state', str(Path.home() / 'imaginarium_conversation.json'))
        project_root = Path(str(self.get_parameter('config').value)).resolve().parent
        sys.path.insert(0, str(project_root))
        from imaginarium.cli import bootstrap
        from imaginarium.subjects import SubjectMap, resolve_subject
        from imaginarium.story_cache import MultiLanguageStoryCache
        from imaginarium.tts import synthesize
        from imaginarium.audio_io import play_audio
        from imaginarium.conversation import DeviceConversation, choose_available_story_index, story_prompt
        self.resolve_subject = resolve_subject
        self.MultiLanguageStoryCache = MultiLanguageStoryCache
        self.synthesize = synthesize
        self.play_audio = play_audio
        self.DeviceConversation = DeviceConversation
        self.choose_available_story_index = choose_available_story_index
        self.story_prompt = story_prompt
        device_id = str(self.get_parameter('device_id').value)
        state_path = Path(str(self.get_parameter('conversation_state').value))
        self.conversation_state = self.DeviceConversation.load(state_path, device_id=device_id)
        self.conversation_state_path = state_path

        self.config = bootstrap(str(self.get_parameter('config').value))
        self.lang = str(self.get_parameter('language').value)
        self.enabled = True
        self.subject_map = None
        self.create_subscription(String, 'device/power', self.power, 10)
        self.create_subscription(String, 'toy/profile', self.tell_profile_story, 10)
        self.create_subscription(String, 'conversation/request', self.conversation, 10)
        self.story_pub = self.create_publisher(String, 'toy/story_event', 10)
        self.status_pub = self.create_publisher(String, 'story/status', 10)
        try:
            self.subject_map = SubjectMap.load(self.config.paths.subject_map)
            self.publish_status('ready', 'Subject map loaded')
        except Exception as exc:
            self.publish_status('degraded', f'Story assets unavailable: {exc}')
            self.get_logger().warn(str(exc))

    def power(self, msg):
        self.enabled = msg.data != 'off'

    def tell_profile_story(self, msg):
        if not self.enabled:
            return
        if self.subject_map is None:
            self.publish_status('degraded', 'Story subject map missing')
            self.get_logger().warn('Story subject map missing')
            return
        profile = json.loads(msg.data)
        toy_id = str(profile.get('toy_id', ''))
        if toy_id:
            self.conversation_state.mark_seen(toy_id)
            axis = self.conversation_state.next_axis()
            self.conversation_state.save(self.conversation_state_path)
            prompt = self.story_prompt(toy_id, axis, self.conversation_state.seen_toy_ids, self.conversation_state.preferred_language)
            self.publish_status('waiting_for_child', prompt)
            return
        try:
            resolution = self.resolve_subject(
                main_class=profile['main_class'], main_confidence=profile['confidence']['main'],
                sub_class=profile['sub_class'] if profile['sub_class'] != profile['main_class'] else None,
                sub_confidence=profile['confidence']['sub'], subject_map=self.subject_map,
                min_main_confidence=self.config.story.min_main_confidence,
                min_sub_confidence=self.config.story.min_sub_confidence)
            cache = self.MultiLanguageStoryCache.load({self.lang: self.config.language(self.lang).story_pool})
            pick = cache.pick_synced(resolution.pool_key, self.config.cache, languages=[self.lang])
            if pick is None:
                raise RuntimeError('No story available for ' + resolution.pool_key)
            story = pick.stories[self.lang]
            out = self.config.paths.audio_dir / ('ros2_' + profile['toy_id'].replace(' ', '_') + '_' + str(pick.index) + '.wav')
            self.synthesize(story.text, out, self.config.language(self.lang).tts)
            self.play_audio(self.config.audio, out)
            event = {'event_type':'story_started','toy_id':profile['toy_id'],'pool_key':resolution.pool_key,
                     'story_index':pick.index,'text':story.text,'audio':str(out)}
            m = String(); m.data=json.dumps(event,ensure_ascii=False); self.story_pub.publish(m)
        except Exception as exc:
            self.get_logger().error('Storytelling failed: %s', exc)

    def conversation(self, msg):
        if not self.enabled:
            return
        text = msg.data.lower()
        if any(word in text for word in ('smetti', 'stop', 'basta')):
            self.publish_status('paused', 'Conversation paused')
            return

        state = self.conversation_state
        affirmative = any(word in text for word in ('si', 'sì', 'yes', 'ok', 'vai', 'racconta', 'continu'))
        negative = any(word in text for word in ('no', 'non', 'basta', 'non ora'))

        if state.current_toy_id and affirmative:
            axis = state.next_axis()
            status = String()
            status.data = json.dumps({
                'mode': 'story_ready',
                'toy_id': state.current_toy_id,
                'axis': axis,
                'text': f'Va bene. Racconto una storia nuova su {state.current_toy_id}, dedicata alla {axis}.',
            }, ensure_ascii=False)
            self.status_pub.publish(status)
            state.chapter_count += 1
            state.save(self.conversation_state_path)
            return

        if negative:
            self.publish_status('waiting', 'Va bene. Posso proporre un’altra storia dopo.')
            return

        toy_id = state.current_toy_id
        if toy_id:
            prompt = self.story_prompt(toy_id, 'curiosita', state.seen_toy_ids, state.preferred_language)
        else:
            prompt = 'Saluta un giocattolo e mettilo davanti alla telecamera: posso conoscerlo e raccontare una sua storia.'
        self.publish_status('waiting_for_child', prompt)

    def publish_status(self, state, detail):
        msg = String()
        msg.data = json.dumps({'state': state, 'detail': detail}, ensure_ascii=False)
        self.status_pub.publish(msg)


def main():
    rclpy.init()
    node=StorytellingNode()
    rclpy.spin(node)
    node.destroy_node(); rclpy.shutdown()

if __name__=='__main__':
    main()

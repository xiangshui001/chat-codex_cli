"""Continue partial API replies without executing truncated tool requests."""
import json
import time

from .mvp0_runner import MvpError


class ResponseRecovery:
    def __init__(self, registry, record=lambda *_: None):
        self.registry, self.record = registry, record
        self.output_limit = registry.limits['max_output_tokens']
        self.count = 0
        self.pulse = lambda: None

    def call(self, client, chosen, history, tools, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MvpError('execution_timeout')
        kwargs = {'timeout': remaining}
        if self.output_limit != self.registry.limits['max_output_tokens']:
            kwargs['max_output_tokens'] = self.output_limit
        try:
            # Keep the control inbox responsive even while an unbounded HTTP request waits.
            import copy
            import queue
            import threading
            result_queue=queue.Queue()
            snapshot=copy.deepcopy(history)
            def invoke():
                try:result_queue.put((True,client.call(chosen,snapshot,tools,**kwargs)))
                except Exception as exc:result_queue.put((False,exc))
            threading.Thread(target=invoke,daemon=True).start()
            while True:
                self.pulse()
                if time.monotonic()>=deadline:raise MvpError('execution_timeout')
                try:ok,result=result_queue.get(timeout=.2)
                except queue.Empty:continue
                if ok:return result
                raise result
        except MvpError as exc:
            if str(exc) not in {'incomplete_model_response', 'empty_model_response', 'invalid_json',
                                'model_transport_failed', 'model_request_timeout',
                                'invalid_model_response', 'invalid_model_tool_call',
                                'model_http_408','model_http_409','model_http_425','model_http_429',
                                'model_http_400','model_http_401','model_http_403','model_http_404','model_api_key_missing',
                                'model_context_window_full','model_output_parameter_rejected',
                                'model_http_500','model_http_502','model_http_503','model_http_504'}:
                raise
            # Local tools have not run for this response. This is a continuation request, not a tool replay.
            return {'text': '', 'calls': [], 'history': [], 'incomplete_reason': str(exc),'diagnostic':getattr(exc,'diagnostic',None)}

    def continue_response(self, result, history, deadline):
        reason = result.get('incomplete_reason')
        if not reason and not result['calls'] and not result['text'].strip():
            reason = 'empty_model_response'
        if not reason:
            return False
        self.count += 1
        previous_limit = self.output_limit
        if reason == 'output_limit':
            ceiling = self.registry.limits['recovery_max_output_tokens']
            self.output_limit = (self.output_limit or 16384) * 2
            if ceiling is not None:
                self.output_limit = min(self.output_limit, ceiling)
        history.extend(result['history'])
        continuation={'role': 'user', 'content':
            'The previous API reply was incomplete or empty and is not a final answer. '
            'Continue the current task using the completed conversation and tool results above. '
            'No tool calls from that incomplete reply were executed. Reissue any still-needed tool calls '
            'with complete valid JSON; do not repeat operations whose successful tool results are already recorded. '
            'Write the requested artifact before giving a complete final answer. For text-only requests, '
            'return a complete consolidated answer, not only the tail of the previous partial response. '
            'Prefer concise replies and small tool batches.'}
        if not history or history[-1] != continuation:
            history.append(continuation)
        self.record('api_response_recovery', {'reason': reason, 'continuation': self.count,
                    'previous_output_tokens': previous_limit, 'output_tokens': self.output_limit,
                    'partial_text_retained': bool(result['text']),**({'diagnostic':result['diagnostic']} if result.get('diagnostic') else {})})
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MvpError('execution_timeout')
        # Back off repeated empty replies instead of rapidly spending tokens on a broken gateway.
        if not result['text']:
            wake=time.monotonic()+min(2 ** min(self.count - 1, 5),30,remaining)
            while time.monotonic()<wake:
                self.pulse();time.sleep(min(.2,wake-time.monotonic()))
        return True

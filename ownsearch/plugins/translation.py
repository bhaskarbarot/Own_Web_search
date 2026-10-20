"""Argos uses only explicitly installed local language packs; no automatic downloads."""
class TranslationProvider:
    name='translation_local'
    accepts_language=True
    def __init__(self,engine):self.engine=engine
    def search(self,query,deadline):
        language=None
        if isinstance(query,tuple):query,language=query
        import time
        from argostranslate import translate
        from ..language import identify
        source=(language or identify(query)['language']).split('-')[0]
        target=self.engine.settings.translation_target
        if source==target:return []
        languages=translate.get_installed_languages()
        src=next((l for l in languages if l.code==source),None)
        dst=next((l for l in languages if l.code==target),None)
        if not src or not dst:raise RuntimeError('Required local translation pack is missing')
        translated=src.get_translation(dst).translate(query)
        if time.monotonic()>=deadline:return []
        response=self.engine.search(translated,live=False,use_cache=False,_allow_variants=False,_allow_plugins=False,
            timeout_ms=max(1,int((deadline-time.monotonic())*1000)))
        return [dict(r,provider=self.name,providers=[self.name],translated_query=translated) for r in response['results']]

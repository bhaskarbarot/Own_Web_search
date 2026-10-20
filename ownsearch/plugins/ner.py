"""Optional locally installed spaCy pipeline. Does not claim to link knowledge-base IDs."""
class NER:
    def __init__(self,path):self.path=path;self.model=None
    name="ner_local"
    def search(self,payload,deadline):
        return self.mentions(payload)

    def mentions(self,text):
        if self.model is None:
            import spacy
            self.model=spacy.load(self.path,exclude=['parser','lemmatizer'])
        return [{'text':e.text,'start':e.start_char,'end':e.end_char,'type':e.label_} for e in self.model(text).ents]

from evalkit import grade, Fixture
from prompts import AnswerResult

f = Fixture(id="x", scenario="", question="q?", turns=[], expect={"no_conclusion": True})
r = AnswerResult(answer="the root cause is definitely the metrics buffer leak",
                 answer_confidence="high", no_conclusion=True)
print("#2 no_conclusion + confident invented answer ->", grade(f, r))

print("#3 empty-expect, arbitrary answer            ->",
      grade(Fixture(id="y", scenario="", question="q?", turns=[], expect={}),
            AnswerResult(answer="literally anything", answer_confidence="high")))

print("#3b unrecognized expect key -> vacuous pass  ->",
      grade(Fixture(id="z", scenario="", question="q?", turns=[], expect={"conclusionz_contains": ["nope"]}),
            AnswerResult(answer="wrong")))

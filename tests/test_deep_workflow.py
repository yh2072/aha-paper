import unittest
from app.pipeline import deep_script

class DeepEditorialTests(unittest.TestCase):
    def outline(self):
        scenes=[]
        for i in range(10):
            scenes.append({'segment_title':f'章节{i+1}','text':'实验设计、比较基线、定量结果与研究局限需要放在同一个证据链中解释。'*9,
                'figure':f'fig_{i+1}.png' if i<3 else None,'source_pages':[i+1]})
        return {'title':'研究机制与证据','chapters':scenes}
    def figs(self):return [{'file':f'fig_{i+1}.png','page':i+1}for i in range(3)]
    def test_short_summary_cannot_pass_as_deep_article(self):
        outline=self.outline()
        for scene in outline['chapters']:scene['text']='只有结论。'
        with self.assertRaisesRegex(ValueError,'字'):deep_script.validate_outline(outline,self.figs(),15)
    def test_sources_are_required_for_every_chapter(self):
        outline=self.outline();outline['chapters'][2]['source_pages']=[]
        with self.assertRaisesRegex(ValueError,'来源页码'):deep_script.validate_outline(outline,self.figs(),15)
    def test_missing_figures_fail_instead_of_decorative_substitution(self):
        outline=self.outline()
        for scene in outline['chapters']:scene['figure']=None
        with self.assertRaisesRegex(ValueError,'至少3张'):deep_script.validate_outline(outline,self.figs(),15)
    def test_fake_source_page_is_rejected(self):
        outline=self.outline();outline['chapters'][0]['source_pages']=[999]
        with self.assertRaises(ValueError):deep_script.validate_outline(outline,self.figs(),15)
    def test_absolute_gain_keeps_ordinary_percentages_intact(self):
        result=deep_script._canonical('解释76%的可解释方差。绝对准确率最高提升了约13%。取得13.2%的绝对准确率提升。准确率从30%提升到43%。')
        self.assertIn('76%',result);self.assertIn('13个百分点',result);self.assertIn('13.2个百分点',result)
        self.assertIn('从30%提升到43%',result)
    def test_valid_deep_outline_keeps_full_text_and_figures(self):
        outline=self.outline();board=deep_script.validate_outline(outline,self.figs(),15)
        self.assertEqual(len(board['scenes']),10)
        self.assertEqual(board['total_chars'],sum(len(s['text'])for s in outline['chapters']))
        self.assertEqual(board['scenes'][0]['source_pages'],[1])

if __name__=='__main__':unittest.main()

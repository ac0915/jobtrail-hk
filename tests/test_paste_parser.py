"""Shared parser regressions; no network or database."""
import pytest
from app.paste_parser import build_paste_preview, split_sections

@pytest.mark.parametrize('heading', ['Requirements', 'Requirements:', 'Requirements：', 'REQUIREMENTS;', 'Requirements；', '• Requirements:'])
def test_heading_variants(heading):
    assert split_sections(heading + '\nPython and C++')['requirements'] == 'Python and C++'

@pytest.mark.parametrize('marker', ['Jobs Description', 'Job Description:', 'JOBS DESCRIPTION；'])
def test_ct_header_and_footer(marker):
    text = ('Job ref no.: EX-1\nPosted on 7d ago\nNew Tab\nAuthority\nSoftware Engineer\nAuthority\n' + marker +
            '\nCompany Overview\nResponsibilities\nBuild systems.\nRequirements:\nPython and SQL.\n'
            'A three-year employment contract will be offered.\nInterested parties apply via CTgoodjobs\nSkills\nPower BI')
    result = build_paste_preview(text)
    job = result['job']
    assert job['title'] == 'Software Engineer'
    assert job['company'] == 'Authority'
    assert job['source'] == 'CTgoodjobs'
    assert job['requirements'] == 'Python and SQL.'
    assert 'Power BI' in job['description']
    assert result['raw_text'] == text

@pytest.mark.parametrize('label', ['應届畢業生', '應屆畢業生', '合約更新, 全職', 'An unfamiliar label'])
def test_indeed_optional_labels(label):
    text = ('Developer\nExample Ltd\nHong Kong\n' + label + '\n透過公司網站應徵\n職位詳情\n未提供薪酬資料\n完整職位描述\n'
            'Job description:\nWhat you will do:\nBuild systems.\nWhat you will need:\nPython.\nD&I Statement\nOther text.')
    result = build_paste_preview(text)
    assert result['can_save']
    assert result['job']['title'] == 'Developer'
    assert result['job']['salary'] is None
    assert result['job']['requirements'] == 'Python.'


def test_sales_duplicate_description_heading():
    text = ('Sales Specialist-IT Digital Signage\n[iSignage Limited](https://hk.indeed.com/cmp/example)\n•\nKwun Tong, Kowloon\n'
            '•\n月薪 $25,000 起\n[立即申請](https://smartapply.indeed.com/example)\n職位詳情\n月薪 $25,000 起\n全職\n'
            '完整職位描述\nJob description:\nSell solutions.\nRequirements:\nUniversity graduated\nFringe Benefits to successful candidate\nMedical insurance')
    job = build_paste_preview(text)['job']
    assert job['title'] == 'Sales Specialist-IT Digital Signage'
    assert job['company'] == 'iSignage Limited'
    assert job['salary'] == '月薪 $25,000 起'
    assert job['requirements'] == 'University graduated'
    assert 'Sell solutions.' in job['description']


def test_unknown_layout_retains_text():
    text = 'Unfamiliar layout\nOriginal text with C++ and C#;'
    result = build_paste_preview(text)
    assert result['result'] == 'partial'
    assert not result['can_save']
    assert result['job']['description'] == text
    assert result['raw_text'] == text
    assert result['job']['source'] is None


def test_multiple_listings_are_not_combined():
    listing = 'Developer\nExample Ltd\nJobs Description\nCompany Overview\nResponsibilities\nBuild\nRequirements\nPython'
    result = build_paste_preview(listing + '\n' + listing.replace('Developer', 'Analyst'))
    assert result['result'] == 'partial'
    assert result['job']['title'] is None
    assert result['job']['salary'] is None


def test_recommendation_salary_is_not_borrowed():
    text = ('Recommended Developer\nOther Ltd\nHong Kong\n$99,000\nNew selected company Ltd\n立即申請\n職位詳情\n'
            '未提供薪酬資料\n來源於Kowloon\n完整職位描述\nSelected job content')
    result = build_paste_preview(text)
    assert result['job']['title'] is None
    assert result['job']['salary'] is None


def test_jobsdb_paste_compatibility():
    text = 'Employer site\nDeveloper\nExample Ltd\nHong Kong\n$20,000\nResponsibilities\nBuild apps\nRequirements\nPython\nReport this job advert'
    job = build_paste_preview(text)['job']
    assert job['title'] == 'Developer'
    assert job['source'] == 'JobsDB'
    assert job['salary'] == '$20,000'


def test_length_and_blank_limits():
    with pytest.raises(ValueError):
        build_paste_preview('  ')
    with pytest.raises(ValueError):
        build_paste_preview('x' * 200001)

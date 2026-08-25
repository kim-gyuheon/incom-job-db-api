from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(BASE_DIR)
SEARCH_DIRS = (
    os.getcwd(),
    BASE_DIR,
    os.path.join(BASE_DIR, "data"),
    os.path.join(REPO_DIR, "data"),
    os.path.join(REPO_DIR, "data", "job-scores"),
    os.path.join(os.getcwd(), "data"),
    os.path.join(os.getcwd(), "data", "job-scores"),
)


def resolve_path(*candidates: str) -> str | None:
    for cand in candidates:
        if not cand:
            continue
        if os.path.isabs(cand):
            if os.path.exists(cand):
                return cand
            hits = sorted(glob.glob(cand))
            if hits:
                return hits[0]
            continue
        for base in SEARCH_DIRS:
            full = os.path.join(base, cand)
            if os.path.exists(full):
                return full
            hits = sorted(glob.glob(full))
            if hits:
                return hits[0]
    return None


def describe_search() -> str:
    return "\n".join(f"    - {os.path.abspath(d)}" for d in dict.fromkeys(SEARCH_DIRS))


@dataclass(frozen=True)
class Axis:
    key: str
    label_ko: str
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def candidates(self) -> tuple[str, ...]:
        return (self.key, self.label_ko, *self.aliases)


AXES: tuple[Axis, ...] = (
    Axis("성격_성취_노력", "성격_성취/노력"),
    Axis("성격_인내", "성격_인내"),
    Axis("성격_책임과_진취성", "성격_책임과 진취성"),
    Axis("성격_리더십", "성격_리더십"),
    Axis("성격_협조", "성격_협조"),
    Axis("성격_타인_배려", "성격_타인 배려"),
    Axis("성격_사회성", "성격_사회성"),
    Axis("성격_자기통제", "성격_자기통제"),
    Axis("성격_스트레스_감내성", "성격_스트레스 감내성"),
    Axis("성격_적응성_융통성", "성격_적응성/융통성"),
    Axis("성격_신뢰성", "성격_신뢰성"),
    Axis("성격_꼼꼼함", "성격_꼼꼼함"),
    Axis("성격_정직성", "성격_정직성"),
    Axis("성격_독립성", "성격_독립성"),
    Axis("성격_혁신", "성격_혁신"),
    Axis("성격_분석적_사고", "성격_분석적 사고"),
    Axis("지식중요도_경영_및_행정", "지식중요도_경영 및 행정"),
    Axis("지식중요도_사무", "지식중요도_사무"),
    Axis("지식중요도_경제와_회계", "지식중요도_경제와 회계"),
    Axis("지식중요도_영업과_마케팅", "지식중요도_영업과 마케팅"),
    Axis("지식중요도_고객서비스", "지식중요도_고객서비스"),
    Axis("지식중요도_인사", "지식중요도_인사"),
    Axis("지식중요도_상품_제조_및_공정", "지식중요도_상품 제조 및 공정"),
    Axis("지식중요도_식품_생산", "지식중요도_식품 생산"),
    Axis("지식중요도_컴퓨터와_전자공학", "지식중요도_컴퓨터와 전자공학"),
    Axis("지식중요도_공학과_기술", "지식중요도_공학과 기술"),
    Axis("지식중요도_디자인", "지식중요도_디자인"),
    Axis("지식중요도_건설_및_건축", "지식중요도_건설 및 건축"),
    Axis("지식중요도_기계", "지식중요도_기계"),
    Axis("지식중요도_산수와_수학", "지식중요도_산수와 수학"),
    Axis("지식중요도_물리", "지식중요도_물리"),
    Axis("지식중요도_화학", "지식중요도_화학"),
    Axis("지식중요도_생물", "지식중요도_생물"),
    Axis("지식중요도_심리", "지식중요도_심리"),
    Axis("지식중요도_사회와_인류", "지식중요도_사회와 인류"),
    Axis("지식중요도_지리", "지식중요도_지리"),
    Axis("지식중요도_의료", "지식중요도_의료"),
    Axis("지식중요도_상담", "지식중요도_상담"),
    Axis("지식중요도_교육_및_훈련", "지식중요도_교육 및 훈련"),
    Axis("지식중요도_국어", "지식중요도_국어"),
    Axis("지식중요도_영어", "지식중요도_영어"),
    Axis("지식중요도_예술", "지식중요도_예술"),
    Axis("지식중요도_역사", "지식중요도_역사"),
    Axis("지식중요도_철학과_신학", "지식중요도_철학과 신학"),
    Axis("지식중요도_안전과_보안", "지식중요도_안전과 보안"),
    Axis("지식중요도_법", "지식중요도_법"),
    Axis("지식중요도_통신", "지식중요도_통신"),
    Axis("지식중요도_의사소통과_미디어", "지식중요도_의사소통과 미디어"),
    Axis("지식중요도_운송", "지식중요도_운송"),
    Axis("지식수준_경영_및_행정", "지식수준_경영 및 행정"),
    Axis("지식수준_사무", "지식수준_사무"),
    Axis("지식수준_경제와_회계", "지식수준_경제와 회계"),
    Axis("지식수준_영업과_마케팅", "지식수준_영업과 마케팅"),
    Axis("지식수준_고객서비스", "지식수준_고객서비스"),
    Axis("지식수준_인사", "지식수준_인사"),
    Axis("지식수준_상품_제조_및_공정", "지식수준_상품 제조 및 공정"),
    Axis("지식수준_식품_생산", "지식수준_식품 생산"),
    Axis("지식수준_컴퓨터와_전자공학", "지식수준_컴퓨터와 전자공학"),
    Axis("지식수준_공학과_기술", "지식수준_공학과 기술"),
    Axis("지식수준_디자인", "지식수준_디자인"),
    Axis("지식수준_건설_및_건축", "지식수준_건설 및 건축"),
    Axis("지식수준_기계", "지식수준_기계"),
    Axis("지식수준_산수와_수학", "지식수준_산수와 수학"),
    Axis("지식수준_물리", "지식수준_물리"),
    Axis("지식수준_화학", "지식수준_화학"),
    Axis("지식수준_생물", "지식수준_생물"),
    Axis("지식수준_심리", "지식수준_심리"),
    Axis("지식수준_사회와_인류", "지식수준_사회와 인류"),
    Axis("지식수준_지리", "지식수준_지리"),
    Axis("지식수준_의료", "지식수준_의료"),
    Axis("지식수준_상담", "지식수준_상담"),
    Axis("지식수준_교육_및_훈련", "지식수준_교육 및 훈련"),
    Axis("지식수준_국어", "지식수준_국어"),
    Axis("지식수준_영어", "지식수준_영어"),
    Axis("지식수준_예술", "지식수준_예술"),
    Axis("지식수준_역사", "지식수준_역사"),
    Axis("지식수준_철학과_신학", "지식수준_철학과 신학"),
    Axis("지식수준_안전과_보안", "지식수준_안전과 보안"),
    Axis("지식수준_법", "지식수준_법"),
    Axis("지식수준_통신", "지식수준_통신"),
    Axis("지식수준_의사소통과_미디어", "지식수준_의사소통과 미디어"),
    Axis("지식수준_운송", "지식수준_운송"),
)

AXIS_KEYS: tuple[str, ...] = tuple(a.key for a in AXES)
AXIS_LABELS_KO: tuple[str, ...] = tuple(a.label_ko for a in AXES)
N_AXES: int = len(AXES)
AXIS_MIN, AXIS_MAX = 0.0, 7.0


def axis_index(key: str) -> int:
    return AXIS_KEYS.index(key)


def _norm(name: str) -> str:
    return re.sub(r"[\s()\[\]·/_\-.,]", "", str(name)).lower()


@dataclass(frozen=True)
class JobSourceConfig:
    path: str = "직무역량_KNOW_82축.csv"
    fallback_globs: tuple[str, ...] = (
        "직무역량*KNOW*82축*.csv",
        "직무역량*최종점수*.csv",
        "직무역량*최종점수*.xls*",
        "*KNOW*82축*.csv",
        "*최종점수*.csv",
        "*최종점수*.xls*",
    )
    sheet: str | int = 0
    csv_glob: str = "job_*_v2_final.csv"

    id_columns: tuple[str, ...] = ("직무ID", "job_id", "ID")
    name_columns: tuple[str, ...] = ("직업명", "job_name", "job")
    second_category_columns: tuple[str, ...] = ("중분류", "second_category")
    third_category_columns: tuple[str, ...] = ("소분류", "third_category")
    status_columns: tuple[str, ...] = ("status", "검수상태")
    precision_columns: tuple[str, ...] = ("정밀도유형", "precision_type")

    def locate(self) -> str:
        if os.path.isdir(self.path):
            return self.path
        found = resolve_path(self.path, *self.fallback_globs)
        if found is None:
            raise FileNotFoundError(
                f"직무 파일을 찾지 못했습니다: {self.path}\n"
                f"  다음 위치를 찾아봤습니다:\n{describe_search()}\n"
                f"  파일을 이 중 한 곳에 두거나, --source 로 전체 경로를 지정하세요.\n"
                f'    python build_db.py --source "C:/경로/직무역량_KNOW_82축.csv"'
            )
        return found


JOB_SOURCE = JobSourceConfig()

BARRIER_MATRIX_NAME = "barrier-review-combined.csv"
BARRIER_MATRIX_GLOBS = ("barrier-review-combined.csv", "d2_review_matrix*.csv", "*review_matrix*.csv")


def locate_barrier_matrix(path: str | None = None) -> str | None:
    if path:
        return resolve_path(path)
    return resolve_path(BARRIER_MATRIX_NAME, *BARRIER_MATRIX_GLOBS)


COL_DRAFT = "초안_판정"
COL_REVIEW1 = "검수_판정(추천에서 뺌 / 그대로 추천)"
COL_REVIEW2 = "검수2_판정(동의 / 추천에서 뺌 / 그대로 추천)"

VERDICT_EXCLUDE = "추천에서 뺌"
VERDICT_KEEP_EDGE = "그대로 추천(경계)"
VERDICT_AGREE = "동의"

CATEGORY_BY_GROUP = {
    "01": "건설·기능",
    "02": "사무·관리",
    "03": "공안·교육·법률·복지",
    "04": "농림어업",
    "05": "서비스·조리·미용",
    "06": "보건·의료",
    "07": "제조·정비",
    "08": "공학·연구·IT",
    "09": "판매·운송",
    "10": "예술·체육·미디어",
}

STATUS_ENRICH: bool = True


@dataclass(frozen=True)
class Dialect:
    real_type: str = "REAL"
    text_type: str = "TEXT"
    int_type: str = "INTEGER"
    now_expr: str = "datetime('now')"
    placeholder: str = "?"


DIALECTS = {
    "sqlite": Dialect(),
    "postgres": Dialect(
        real_type="DOUBLE PRECISION",
        int_type="INTEGER",
        now_expr="CURRENT_TIMESTAMP",
        placeholder="%s",
    ),
}


@dataclass(frozen=True)
class DbConfig:
    path: str = "career.db"
    dialect: str = "sqlite"

    table_jobs: str = "job_vectors"
    table_axes: str = "axes"
    table_barriers: str = "barriers"
    table_job_barriers: str = "job_barriers"

    col_job_id: str = "job_id"
    col_job_name: str = "job_name"
    col_category: str = "category"
    col_recommendable: str = "is_recommendable"
    col_barrier_id: str = "barrier_id"
    col_excluded: str = "is_excluded"

    @property
    def sql(self) -> Dialect:
        return DIALECTS[self.dialect]

    def locate(self) -> str:
        if os.path.isabs(self.path):
            return self.path
        found = resolve_path(self.path)
        return found or os.path.join(BASE_DIR, self.path)


def get_db_config(path: str | None = None, dialect: str | None = None) -> DbConfig:
    return DbConfig(
        path=path or os.environ.get("CAREER_DB_PATH", "career.db"),
        dialect=dialect or os.environ.get("CAREER_DB_DIALECT", "sqlite"),
    )


DB = get_db_config()


if __name__ == "__main__":
    print(f"축 {N_AXES}개")
    for i, a in enumerate(AXES):
        print(f"  [{i}] {a.key:<14} {a.label_ko}")
    print(f"\n탐색 경로:\n{describe_search()}")
    try:
        print(f"\n직무 파일 : {JOB_SOURCE.locate()}")
    except FileNotFoundError as e:
        print(f"\n{e}")
    print(f"barrier   : {locate_barrier_matrix()}")
    print(f"DB        : {DB.locate()} ({DB.dialect})")

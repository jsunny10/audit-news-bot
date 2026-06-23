#!/usr/bin/env python3
"""
기존 JSON 파일들을 월별 폴더로 마이그레이션하는 스크립트

기존 구조: docs/data/2026-06-23.json
새 구조:   docs/data/2026-06/2026-06-23.json
"""

import os
import shutil
import json
from pathlib import Path

def migrate_to_monthly_folders():
    data_dir = Path('docs/data')

    if not data_dir.exists():
        print("❌ docs/data 폴더가 없습니다.")
        return

    # data 폴더의 모든 JSON 파일 찾기 (index.json 제외)
    json_files = [f for f in data_dir.glob('*.json') if f.name != 'index.json']

    if not json_files:
        print("✅ 마이그레이션할 파일이 없습니다.")
        return

    print(f"📦 {len(json_files)}개의 파일을 마이그레이션합니다...\n")

    moved_count = 0
    for json_file in json_files:
        # 파일명에서 년-월 추출 (예: 2026-06-23.json -> 2026-06)
        filename = json_file.stem  # 2026-06-23

        if len(filename) >= 7 and filename[4] == '-' and filename[7] == '-':
            year_month = filename[:7]  # 2026-06

            # 월별 폴더 생성
            month_dir = data_dir / year_month
            month_dir.mkdir(exist_ok=True)

            # 파일 이동
            new_path = month_dir / json_file.name

            if not new_path.exists():
                shutil.move(str(json_file), str(new_path))
                print(f"✅ 이동: {json_file.name} → {year_month}/{json_file.name}")
                moved_count += 1
            else:
                print(f"⚠️  건너뜀: {new_path} (이미 존재)")
        else:
            print(f"⚠️  형식 오류: {json_file.name} (년-월-일 형식 아님)")

    print(f"\n{'='*60}")
    print(f"✨ 마이그레이션 완료! {moved_count}개 파일 이동됨")
    print(f"{'='*60}")

    # 폴더 구조 출력
    print("\n📁 새로운 폴더 구조:")
    for month_folder in sorted(data_dir.glob('*/')):
        file_count = len(list(month_folder.glob('*.json')))
        print(f"  {month_folder.name}/ ({file_count}개 파일)")


if __name__ == "__main__":
    migrate_to_monthly_folders()

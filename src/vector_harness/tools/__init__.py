"""默认工具：读文件、改文件、在工作目录里跑命令，以及四则运算。

这里的“默认”指不依赖任何模式就能使用，只靠 ``root`` 或什么都不靠。模式自己
长出来的工具（``read_skill``、``remember``、``delegate``、``update_todos``、
``submit_verdict``）留在 ``patterns/`` 各自的文件里：它们要读该模式的状态，
搬进来就得让 ``tools`` 反过来导入 ``patterns``，而这条方向由
``tests/test_import_boundary.py`` 禁止。新增通用能力放这里，新增模式放那边。
"""

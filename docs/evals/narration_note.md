**A bug this measurement found.** All 8 films were made while the Picture Checker's rejections were silently
ignored: the models answer with picture ids missing their `:moment` ending, so none of the 20 pictures the
checker wanted out of these films was removed (its narration rewrites did apply). Fixed on 2026-10-31
(`checker._match_id`); films made from now on drop those pictures, so this table is the before.

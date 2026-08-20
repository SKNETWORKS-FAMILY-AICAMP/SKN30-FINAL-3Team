resource "aws_iam_group" "team_readonly" {
  name = "team-readonly"
  path = "/"
}

resource "aws_iam_group_policy_attachment" "team_readonly" {
  group      = aws_iam_group.team_readonly.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/ReadOnlyAccess"
}

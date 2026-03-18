from __future__ import annotations


VIEWER_OVERVIEW_QUERY = """
query ViewerOverview($from: DateTime!, $to: DateTime!, $repoFirst: Int!) {
  viewer {
    login
    name
    url
    avatarUrl
    contributionsCollection(from: $from, to: $to) {
      restrictedContributionsCount
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      contributionCalendar {
        totalContributions
        weeks {
          firstDay
          contributionDays {
            date
            weekday
            contributionCount
            color
          }
        }
      }
      commitContributionsByRepository(maxRepositories: $repoFirst) {
        repository {
          id
          name
          nameWithOwner
          url
          description
          isPrivate
          isFork
          stargazerCount
          forkCount
          pushedAt
          owner { login }
          primaryLanguage { name color }
        }
        contributions(first: 1) { totalCount }
      }
      issueContributionsByRepository(maxRepositories: $repoFirst) {
        repository {
          id
          name
          nameWithOwner
          url
          description
          isPrivate
          isFork
          stargazerCount
          forkCount
          pushedAt
          owner { login }
          primaryLanguage { name color }
        }
        contributions(first: 1) { totalCount }
      }
      pullRequestContributionsByRepository(maxRepositories: $repoFirst) {
        repository {
          id
          name
          nameWithOwner
          url
          description
          isPrivate
          isFork
          stargazerCount
          forkCount
          pushedAt
          owner { login }
          primaryLanguage { name color }
        }
        contributions(first: 1) { totalCount }
      }
      pullRequestReviewContributionsByRepository(maxRepositories: $repoFirst) {
        repository {
          id
          name
          nameWithOwner
          url
          description
          isPrivate
          isFork
          stargazerCount
          forkCount
          pushedAt
          owner { login }
          primaryLanguage { name color }
        }
        contributions(first: 1) { totalCount }
      }
    }
    repositories(first: $repoFirst, orderBy: {field: PUSHED_AT, direction: DESC}) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        id
        name
        nameWithOwner
        url
        description
        isPrivate
        isFork
        stargazerCount
        forkCount
        pushedAt
        owner { login }
        primaryLanguage { name color }
        languages(first: 6, orderBy: {field: SIZE, direction: DESC}) {
          totalSize
          edges {
            size
            node { name color }
          }
        }
      }
    }
  }
  rateLimit {
    cost
    remaining
    resetAt
  }
}
""".strip()


REPOSITORY_DETAILS_QUERY = """
query RepositoryDetails($ids: [ID!]!) {
  nodes(ids: $ids) {
    __typename
    ... on Repository {
      id
      name
      nameWithOwner
      url
      description
      isPrivate
      isFork
      stargazerCount
      forkCount
      pushedAt
      owner { login }
      primaryLanguage { name color }
      languages(first: 6, orderBy: {field: SIZE, direction: DESC}) {
        totalSize
        edges {
          size
          node { name color }
        }
      }
    }
  }
  rateLimit {
    cost
    remaining
    resetAt
  }
}
""".strip()


SEARCH_PULL_REQUESTS_QUERY = """
query SearchPullRequests($query: String!, $first: Int!, $after: String) {
  search(type: ISSUE, query: $query, first: $first, after: $after) {
    issueCount
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      ... on PullRequest {
        id
        number
        title
        url
        state
        createdAt
        mergedAt
        additions
        deletions
        repository {
          id
          name
          nameWithOwner
          url
          description
          isPrivate
          isFork
          stargazerCount
          forkCount
          pushedAt
          owner { login }
          primaryLanguage { name color }
        }
      }
    }
  }
  rateLimit {
    cost
    remaining
    resetAt
  }
}
""".strip()


SEARCH_ISSUES_QUERY = """
query SearchIssues($query: String!, $first: Int!, $after: String) {
  search(type: ISSUE, query: $query, first: $first, after: $after) {
    issueCount
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      ... on Issue {
        id
        number
        title
        url
        state
        createdAt
        repository {
          id
          name
          nameWithOwner
          url
          description
          isPrivate
          isFork
          stargazerCount
          forkCount
          pushedAt
          owner { login }
          primaryLanguage { name color }
        }
      }
    }
  }
  rateLimit {
    cost
    remaining
    resetAt
  }
}
""".strip()


def build_pr_search_query(login: str, start_date: str, end_date: str) -> str:
    return (
        f"author:{login} is:pr archived:false created:{start_date}..{end_date} "
        "sort:created-desc"
    )


def build_issue_search_query(login: str, start_date: str, end_date: str) -> str:
    return (
        f"author:{login} is:issue archived:false created:{start_date}..{end_date} "
        "sort:created-desc"
    )


def build_merged_pr_search_query(login: str, start_date: str, end_date: str) -> str:
    return (
        f"author:{login} is:pr is:merged archived:false created:{start_date}..{end_date} "
        "sort:created-desc"
    )

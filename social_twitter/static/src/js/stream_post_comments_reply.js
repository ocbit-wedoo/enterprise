/** @odoo-module **/

import { StreamPostCommentsReply } from '@social/js/stream_post_comments_reply';

import { sprintf } from '@web/core/utils/strings';

export class StreamPostCommentsReplyTwitter extends StreamPostCommentsReply {
    setup() {
        super.setup();
        this.state.disabled = !this.canReply;
    }

    get authorPictureSrc() {
        return sprintf('/web/image/social.account/%s/image/48x48', this.props.mediaSpecificProps.accountId);
    }

    get addCommentEndpoint() {
        return sprintf('/social_twitter/%s/comment', this.originalPost.stream_id.raw_value);
    }

    get canReply() {
        if (this.originalPost.is_author.raw_value) {
            // we are the author
            return true;
        }
        const handle = this.props.mediaSpecificProps.twitterUserScreenName;
        const message = this.originalPost.message.raw_value;
        if (new RegExp(`\\B@${RegExp.escape(handle)}\\b`, "i").test(message)) {
            // we are mentioned in the message
            return true;
        }

        const quotedAuthorUrl = this.originalPost.twitter_quoted_tweet_author_link.raw_value;
        if (!quotedAuthorUrl) {
            return false;
        }
        // the handle of the user of the parent tweet is not in the body in the child tweet
        // but we can deduce that information from the `twitter_quoted_tweet_author_link`
        // without adding new field in stable
        return handle === quotedAuthorUrl.split("/").at(-1);
    }
}
